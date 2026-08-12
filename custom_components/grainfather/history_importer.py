from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Literal

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify
from homeassistant.util.unit_conversion import TemperatureConverter

from .api import (
    GrainfatherApiClient,
    GrainfatherApiError,
    GrainfatherBrewSession,
    GrainfatherHistoryPoint,
    GrainfatherSnapshot,
    parse_batch_payload,
    parse_fermentation_device_history_points,
)
from .density import sg_to_plato

_LOGGER = logging.getLogger(__name__)

HISTORY_START_DATE = "2001-01-07"
type HistoryStatisticSeries = tuple[StatisticMetaData, tuple[StatisticData, ...]]

type HistoryMetric = Literal["temperature", "specific_gravity", "plato"]


def batch_statistic_id(entry_id: str, batch_id: int, metric: HistoryMetric) -> str:
    """Return the immutable Recorder statistic ID for a batch metric."""
    return f"grainfather:{slugify(entry_id)}_batch_{batch_id}_{metric}"


def _as_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    timestamp = dt_util.parse_datetime(value)
    if timestamp is None or timestamp.tzinfo is None:
        return None
    return timestamp.astimezone(UTC)


def _batch_name(
    session: GrainfatherBrewSession | None,
    point: GrainfatherHistoryPoint,
    batch_id: int,
    suffix: str,
) -> str:
    recipe_name = session.recipe_name if session is not None else None
    session_name = session.session_name if session is not None else None
    point_recipe_name = point.raw_payload.get("recipe_name") or point.raw_payload.get(
        "recipeName"
    )
    name = recipe_name or session_name or point_recipe_name or f"Batch {batch_id}"
    batch_number = session.batch_number if session is not None else None
    prefix = f"#{batch_number} " if batch_number is not None else ""
    return f"{prefix}{name} {suffix}"


def _metadata(
    entry_id: str,
    batch_id: int,
    name: str,
    metric: HistoryMetric,
) -> StatisticMetaData:
    if metric == "temperature":
        return {
            "statistic_id": batch_statistic_id(entry_id, batch_id, metric),
            "source": "grainfather",
            "name": name,
            "unit_of_measurement": UnitOfTemperature.CELSIUS,
            "unit_class": TemperatureConverter.UNIT_CLASS,
            "has_mean": True,
            "has_sum": False,
            "mean_type": StatisticMeanType.ARITHMETIC,
        }
    unit = "SG" if metric == "specific_gravity" else "°P"
    return {
        "statistic_id": batch_statistic_id(entry_id, batch_id, metric),
        "source": "grainfather",
        "name": name,
        "unit_of_measurement": unit,
        "unit_class": None,
        "has_mean": True,
        "has_sum": False,
        "mean_type": StatisticMeanType.ARITHMETIC,
    }


def _hourly_statistics(
    values_by_hour: Mapping[datetime, list[float]], precision: int
) -> tuple[StatisticData, ...]:
    return tuple(
        {
            "start": hour,
            "mean": round(sum(values) / len(values), precision),
            "min": round(min(values), precision),
            "max": round(max(values), precision),
        }
        for hour, values in sorted(values_by_hour.items())
        if values
    )


def build_hourly_history_statistics(
    points: Iterable[GrainfatherHistoryPoint],
    sessions_by_batch_id: Mapping[int, GrainfatherBrewSession],
    entry_id: str,
    *,
    from_time: datetime | None = None,
) -> tuple[HistoryStatisticSeries, ...]:
    """Aggregate linked Grainfather readings into Recorder-compatible hours."""
    minimum_time = from_time.astimezone(UTC) if from_time is not None else None
    points_by_batch: dict[int, list[tuple[GrainfatherHistoryPoint, datetime]]] = (
        defaultdict(list)
    )
    for point in points:
        if point.brew_session_id is None:
            continue
        timestamp = _as_utc(point.timestamp)
        if timestamp is None or (minimum_time is not None and timestamp < minimum_time):
            continue
        points_by_batch[point.brew_session_id].append((point, timestamp))

    series: list[HistoryStatisticSeries] = []
    for batch_id, batch_points in sorted(points_by_batch.items()):
        session = sessions_by_batch_id.get(batch_id)
        gravity_device_ids = {
            point.device_id
            for point, _ in batch_points
            if point.specific_gravity is not None
        }
        temperature_by_hour: dict[datetime, list[float]] = defaultdict(list)
        gravity_by_hour: dict[datetime, list[float]] = defaultdict(list)
        plato_by_hour: dict[datetime, list[float]] = defaultdict(list)
        first_point = batch_points[0][0]

        for point, timestamp in batch_points:
            hour = timestamp.replace(minute=0, second=0, microsecond=0)
            if point.temperature is not None and (
                not gravity_device_ids or point.device_id in gravity_device_ids
            ):
                temperature_by_hour[hour].append(point.temperature)
            if point.specific_gravity is not None:
                gravity_by_hour[hour].append(point.specific_gravity)
                plato = sg_to_plato(point.specific_gravity)
                if plato is not None:
                    plato_by_hour[hour].append(plato)

        for metric, suffix, values, precision in (
            ("temperature", "Temperature", temperature_by_hour, 2),
            ("specific_gravity", "Specific Gravity", gravity_by_hour, 4),
            ("plato", "Gravity (Plato)", plato_by_hour, 1),
        ):
            statistics = _hourly_statistics(values, precision)
            if statistics:
                series.append(
                    (
                        _metadata(
                            entry_id,
                            batch_id,
                            _batch_name(session, first_point, batch_id, suffix),
                            metric,
                        ),
                        statistics,
                    )
                )
    return tuple(series)


class GrainfatherHistoryImporter:
    """Backfill and refresh hourly Grainfather fermentation statistics."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: GrainfatherApiClient,
        entry: ConfigEntry,
    ) -> None:
        self._hass = hass
        self._api = api
        self._entry = entry

    async def async_import_full_history(self, snapshot: GrainfatherSnapshot) -> None:
        """Import all linked device history without delaying integration startup."""
        sessions = snapshot.brew_sessions
        try:
            payloads = await self._api.async_get_brew_sessions()
        except GrainfatherApiError:
            _LOGGER.warning(
                "Could not fetch Grainfather brew sessions for history import"
            )
        else:
            sessions = tuple(
                session
                for payload in payloads
                if (session := parse_batch_payload(payload)) is not None
            )

        sessions_by_batch_id = _sessions_by_batch_id(sessions)
        device_ids = {
            device_id
            for session in sessions
            for device_id in session.fermentation_device_ids
        }
        device_ids.update(
            device.device_id
            for device in snapshot.fermentation_devices
            if device.device_id is not None
        )
        if not device_ids:
            _LOGGER.debug(
                "No Grainfather fermentation devices available for history import"
            )
            return

        points: list[GrainfatherHistoryPoint] = []
        for device_id in sorted(device_ids):
            payload = await self._async_get_device_history(device_id, sessions)
            if payload is not None:
                points.extend(
                    parse_fermentation_device_history_points(payload, device_id)
                )

        series = build_hourly_history_statistics(
            points, sessions_by_batch_id, self._entry.entry_id
        )
        if not series:
            _LOGGER.debug("No valid linked Grainfather fermentation history to import")
            return
        for metadata, statistics in series:
            async_add_external_statistics(self._hass, metadata, statistics)
        rows = sum(len(statistics) for _, statistics in series)
        batch_ids = {
            metadata["statistic_id"].split("_batch_", 1)[1].split("_", 1)[0]
            for metadata, _ in series
        }
        _LOGGER.info(
            "Imported %s hourly fermentation statistic rows across %s batches",
            rows,
            len(batch_ids),
        )

    @callback
    def async_import_recent_history(self, snapshot: GrainfatherSnapshot) -> None:
        """Refresh the current and immediately preceding UTC statistic hours."""
        now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        from_time = now - timedelta(hours=1)
        until_time = now + timedelta(hours=1)
        points = (
            point
            for device_points in snapshot.fermentation_history_by_device_id.values()
            for point in device_points
            if (timestamp := _as_utc(point.timestamp)) is not None
            and from_time <= timestamp < until_time
        )
        sessions_by_batch_id = _sessions_by_batch_id(snapshot.brew_sessions)
        for metadata, statistics in build_hourly_history_statistics(
            points,
            sessions_by_batch_id,
            self._entry.entry_id,
            from_time=from_time,
        ):
            async_add_external_statistics(self._hass, metadata, statistics)

    async def _async_get_device_history(
        self, device_id: int, sessions: tuple[GrainfatherBrewSession, ...]
    ) -> list[dict] | None:
        try:
            return await self._api.async_get_fermentation_device_history(
                device_id,
                from_date=HISTORY_START_DATE,
                data_format="raw",
                metric=True,
            )
        except GrainfatherApiError:
            retry_date = _earliest_session_date(device_id, sessions)
            if retry_date is not None:
                try:
                    return await self._api.async_get_fermentation_device_history(
                        device_id,
                        from_date=retry_date,
                        data_format="raw",
                        metric=True,
                    )
                except GrainfatherApiError:
                    pass
            _LOGGER.warning(
                "Could not import Grainfather fermentation history for device %s",
                device_id,
            )
            return None


def _sessions_by_batch_id(
    sessions: Iterable[GrainfatherBrewSession],
) -> dict[int, GrainfatherBrewSession]:
    sessions_by_batch_id: dict[int, GrainfatherBrewSession] = {}
    for session in sessions:
        batch_id = _valid_batch_id(session.batch_id)
        if batch_id is not None:
            sessions_by_batch_id[batch_id] = session
    return sessions_by_batch_id


def _valid_batch_id(batch_id: int | str | None) -> int | None:
    try:
        return int(batch_id) if batch_id is not None else None
    except (TypeError, ValueError):
        return None


def _earliest_session_date(
    device_id: int, sessions: Iterable[GrainfatherBrewSession]
) -> str | None:
    dates = [
        timestamp
        for session in sessions
        if device_id in session.fermentation_device_ids
        for value in (session.created_at, session.fermentation_start_date)
        if (timestamp := _as_utc(value)) is not None
    ]
    return min(dates).strftime("%Y-%m-%d") if dates else None
