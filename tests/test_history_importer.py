import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from custom_components.grainfather.api import (
    GrainfatherAccount,
    GrainfatherApiError,
    GrainfatherFermentationDevice,
    GrainfatherHistoryPoint,
    GrainfatherSnapshot,
    parse_batch_payload,
)
from custom_components.grainfather.history_importer import (
    HISTORY_START_DATE,
    GrainfatherHistoryImporter,
    batch_statistic_id,
    build_hourly_history_statistics,
)

HOUR = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _session(batch_id: int, devices: list[int], **overrides: Any):
    payload = {
        "id": batch_id,
        "batch_number": 107,
        "name": "Koji Brut Rice IPA",
        "session_name": "Koji Brut Rice IPA #107",
        "fermentation_devices": devices,
        "created_at": "2026-01-02T08:00:00Z",
    }
    payload.update(overrides)
    session = parse_batch_payload(payload)
    assert session is not None
    return session


def _point(
    device_id: int,
    batch_id: int | None,
    timestamp: str | None,
    temperature: float | None = None,
    gravity: float | None = None,
) -> GrainfatherHistoryPoint:
    return GrainfatherHistoryPoint(
        device_id=device_id,
        brew_session_id=batch_id,
        timestamp=timestamp,
        temperature=temperature,
        specific_gravity=gravity,
        raw_payload={"recipe_name": "Fallback recipe"},
    )


def _series_by_suffix(series):
    return {
        metadata["statistic_id"].rsplit("_", 1)[-1]: (metadata, rows)
        for metadata, rows in series
    }


def test_batch_statistic_id_is_immutable_and_entry_scoped() -> None:
    assert batch_statistic_id("A Very Special Entry", 1415708, "temperature") == (
        "grainfather:a_very_special_entry_batch_1415708_temperature"
    )
    assert batch_statistic_id("A Very Special Entry", 1415708, "plato") == (
        "grainfather:a_very_special_entry_batch_1415708_plato"
    )


def test_build_hourly_history_statistics_aggregates_linked_hydrometer_data() -> None:
    session = _session(1415708, [1, 2])
    points = [
        _point(1, 1415708, "2026-08-10T12:05:00Z", 18.0, 1.0500),
        _point(1, 1415708, "2026-08-10T12:45:00Z", 20.0, 1.0460),
        _point(2, 1415708, "2026-08-10T12:10:00Z", 11.0),
        _point(2, 1415708, "2026-08-10T12:50:00Z", 12.0),
        _point(1, None, "2026-08-10T12:30:00Z", 99.0, 1.1000),
        _point(1, 1415708, "invalid", 99.0, 1.1000),
        _point(1, 1415708, "2026-08-10T12:30:00", 99.0, 1.1000),
        _point(1, 1415708, "2026-08-10T10:30:00Z", 99.0, 1.1000),
    ]

    series = _series_by_suffix(
        build_hourly_history_statistics(
            points,
            {1415708: session},
            "A Very Special Entry",
            from_time=HOUR - timedelta(hours=1),
        )
    )

    assert set(series) == {"temperature", "gravity", "plato"}
    temperature_metadata, temperature_rows = series["temperature"]
    gravity_metadata, gravity_rows = series["gravity"]
    plato_metadata, plato_rows = series["plato"]
    assert temperature_metadata["statistic_id"] == (
        "grainfather:a_very_special_entry_batch_1415708_temperature"
    )
    assert temperature_metadata["name"] == "#107 Koji Brut Rice IPA Temperature"
    assert temperature_metadata["unit_of_measurement"] == "°C"
    assert temperature_metadata["unit_class"] == "temperature"
    assert gravity_metadata["unit_of_measurement"] == "SG"
    assert gravity_metadata["unit_class"] is None
    assert plato_metadata["unit_of_measurement"] == "°P"
    assert temperature_rows == (
        {"start": HOUR, "mean": 19.0, "min": 18.0, "max": 20.0},
    )
    assert gravity_rows == ({"start": HOUR, "mean": 1.048, "min": 1.046, "max": 1.05},)
    assert plato_rows == ({"start": HOUR, "mean": 11.9, "min": 11.4, "max": 12.4},)


def test_build_hourly_history_statistics_retains_controller_only_temperature() -> None:
    session = _session(42, [2])

    series = _series_by_suffix(
        build_hourly_history_statistics(
            [_point(2, 42, "2026-08-10T12:05:00Z", 18.5)],
            {42: session},
            "entry",
        )
    )

    assert set(series) == {"temperature"}
    assert series["temperature"][1][0]["mean"] == 18.5


class _FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    async def async_get_brew_sessions(self) -> list[dict[str, Any]]:
        return [
            {
                "id": 1415708,
                "batch_number": 107,
                "name": "Koji Brut Rice IPA",
                "fermentation_devices": [1, 2, 3],
                "created_at": "2024-01-02T08:00:00Z",
            }
        ]

    async def async_get_fermentation_device_history(
        self, device_id: int, *, from_date: str, data_format: str, metric: bool
    ) -> list[dict[str, Any]]:
        self.calls.append((device_id, from_date))
        assert data_format == "raw"
        assert metric is True
        if device_id == 1 and from_date == HISTORY_START_DATE:
            raise GrainfatherApiError("range rejected")
        if device_id == 3:
            raise GrainfatherApiError("unavailable")
        return [
            {
                "brew_session_id": 1415708,
                "timestamp": "2024-01-02T08:10:00Z",
                "temperature": 19.0,
                "specific_gravity": 1.050,
            }
        ]


def _snapshot(
    *, points_by_device: dict[int, tuple[GrainfatherHistoryPoint, ...]] | None = None
) -> GrainfatherSnapshot:
    return GrainfatherSnapshot(
        account=GrainfatherAccount(None, None, None, None),
        brew_sessions=(),
        fermentation_devices=(
            GrainfatherFermentationDevice(
                device_id=2,
                name="Current",
                fermentation_device_type_id=None,
                linked_brew_session_id=None,
                linked_brew_session_name=None,
                last_heard=None,
                last_specific_gravity=None,
                last_temperature=None,
                is_controller_linked=None,
                raw_payload={},
            ),
        ),
        fermentation_history_by_device_id=points_by_device or {},
    )


def test_full_import_retries_per_device_and_continues(monkeypatch) -> None:
    api = _FakeApi()
    calls = []
    monkeypatch.setattr(
        "custom_components.grainfather.history_importer.async_add_external_statistics",
        lambda hass, metadata, statistics: calls.append((metadata, statistics)),
    )
    importer = GrainfatherHistoryImporter(
        SimpleNamespace(),
        cast(Any, api),
        SimpleNamespace(entry_id="entry"),
    )

    asyncio.run(importer.async_import_full_history(_snapshot()))

    assert api.calls == [
        (1, HISTORY_START_DATE),
        (1, "2024-01-02"),
        (2, HISTORY_START_DATE),
        (3, HISTORY_START_DATE),
        (3, "2024-01-02"),
    ]
    assert calls


def test_recent_import_only_writes_previous_and_current_hours(monkeypatch) -> None:
    session = _session(42, [1])
    points: dict[int, tuple[GrainfatherHistoryPoint, ...]] = {
        1: (
            _point(1, 42, "2026-08-10T10:30:00Z", 1.0),
            _point(1, 42, "2026-08-10T11:30:00Z", 2.0),
            _point(1, 42, "2026-08-10T12:30:00Z", 3.0),
        )
    }
    calls = []
    monkeypatch.setattr(
        "custom_components.grainfather.history_importer.dt_util.utcnow", lambda: HOUR
    )
    monkeypatch.setattr(
        "custom_components.grainfather.history_importer.async_add_external_statistics",
        lambda hass, metadata, statistics: calls.append((metadata, statistics)),
    )
    importer = GrainfatherHistoryImporter(
        SimpleNamespace(),
        cast(Any, SimpleNamespace()),
        SimpleNamespace(entry_id="entry"),
    )
    snapshot = _snapshot(points_by_device=points)
    snapshot.brew_sessions = (session,)

    importer.async_import_recent_history(snapshot)

    assert {row["start"] for _, rows in calls for row in rows} == {
        datetime(2026, 8, 10, 11, tzinfo=UTC),
        HOUR,
    }
