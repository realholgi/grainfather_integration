from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import (
    GrainfatherBrewSession,
    GrainfatherFermentationDevice,
    GrainfatherHistoryPoint,
    GrainfatherSnapshot,
    brew_session_device_identifier,
    brew_session_display_name,
    brew_session_unique_fragment,
    serialize_recipe_ingredients,
)
from .const import (
    BREW_SESSION_STATUS_NAME_BY_CODE,
    CONF_DEFAULT_DENSITY_UNIT,
    DEFAULT_DENSITY_UNIT,
    DOMAIN,
)
from .coordinator import GrainfatherDataUpdateCoordinator
from .density import sg_to_plato
from .history_importer import batch_statistic_id

_MAX_EXPOSED_BATCH_HISTORY_POINTS = 20
_MAX_EXPOSED_DEVICE_HISTORY_POINTS = 5
_MAX_EXPOSED_NOTES_CHARS = 400
_MAX_EXPOSED_INGREDIENTS = 30


@dataclass(frozen=True, kw_only=True)
class GrainfatherSessionSensorDescription(SensorEntityDescription):
    value_fn: Callable[[GrainfatherBrewSession], Any]
    attributes_fn: (
        Callable[[GrainfatherBrewSession, GrainfatherSnapshot], dict[str, Any] | None]
        | None
    ) = None


def _calc_abv(og: float | None, fg: float | None) -> float | None:
    if og is None or fg is None:
        return None
    return round((og - fg) * 131.25, 2)


def _plato_from_session(
    session: GrainfatherBrewSession, attr_name: str
) -> float | None:
    return sg_to_plato(getattr(session, attr_name, None))


def _recipe_value(session: GrainfatherBrewSession, attr_name: str) -> Any:
    recipe = session.recipe
    if recipe is None:
        return None
    return getattr(recipe, attr_name, None)


def _raw_first(session: GrainfatherBrewSession, *keys: str) -> Any:
    for key in keys:
        value = session.raw_payload.get(key)
        if value is not None:
            return value
    return None


def _raw_float(session: GrainfatherBrewSession, *keys: str) -> float | None:
    value = _raw_first(session, *keys)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _priming_sugar_attributes(
    session: GrainfatherBrewSession,
    snapshot: GrainfatherSnapshot,
) -> dict[str, Any]:
    del snapshot
    return {
        "priming_sugar_type": _raw_first(session, "priming_sugar_type"),
        "priming_sugar_amount": _raw_float(session, "priming_sugar_amount"),
    }


def _recipe_info_attributes(
    session: GrainfatherBrewSession,
    snapshot: GrainfatherSnapshot,
) -> dict[str, Any]:
    del snapshot
    recipe = session.recipe
    attributes: dict[str, Any] = {
        "grainfather_entity_type": "recipe",
        "recipe_id": recipe.recipe_id if recipe is not None else session.recipe_id,
        "recipe_name": (recipe.name if recipe is not None else None)
        or session.recipe_name,
        "abv": recipe.abv if recipe is not None else None,
        "ibu": recipe.ibu if recipe is not None else None,
        "srm": recipe.srm if recipe is not None else None,
        "og": recipe.og if recipe is not None else None,
        "fg": recipe.fg if recipe is not None else None,
    }
    attributes.update(serialize_recipe_ingredients(recipe, _MAX_EXPOSED_INGREDIENTS))
    return attributes


SESSION_SENSORS: tuple[GrainfatherSessionSensorDescription, ...] = (
    GrainfatherSessionSensorDescription(
        key="batch_number",
        translation_key="session_batch_number",
        value_fn=lambda s: s.batch_number,
        attributes_fn=lambda s, snapshot: _session_batch_number_attributes(s, snapshot),
    ),
    GrainfatherSessionSensorDescription(
        key="abv",
        translation_key="session_abv",
        native_unit_of_measurement="%vol",
        suggested_display_precision=1,
        value_fn=lambda s: _calc_abv(s.original_gravity, s.final_gravity),
    ),
    GrainfatherSessionSensorDescription(
        key="style",
        translation_key="session_style",
        value_fn=lambda s: s.style_name,
    ),
    GrainfatherSessionSensorDescription(
        key="original_gravity",
        translation_key="session_original_gravity",
        suggested_display_precision=4,
        value_fn=lambda s: s.original_gravity,
    ),
    GrainfatherSessionSensorDescription(
        key="original_gravity_plato",
        translation_key="session_original_gravity_plato",
        native_unit_of_measurement="°P",
        suggested_display_precision=1,
        value_fn=lambda s: _plato_from_session(s, "original_gravity"),
    ),
    GrainfatherSessionSensorDescription(
        key="final_gravity",
        translation_key="session_final_gravity",
        suggested_display_precision=4,
        value_fn=lambda s: s.final_gravity,
    ),
    GrainfatherSessionSensorDescription(
        key="final_gravity_plato",
        translation_key="session_final_gravity_plato",
        native_unit_of_measurement="°P",
        suggested_display_precision=1,
        value_fn=lambda s: _plato_from_session(s, "final_gravity"),
    ),
    GrainfatherSessionSensorDescription(
        key="batch_variant_name",
        translation_key="session_batch_variant_name",
        value_fn=lambda s: s.batch_variant_name,
    ),
    GrainfatherSessionSensorDescription(
        key="recipe_image_url",
        translation_key="session_recipe_image_url",
        value_fn=lambda s: s.recipe_image_url,
    ),
    GrainfatherSessionSensorDescription(
        key="target_abv",
        translation_key="session_target_abv",
        native_unit_of_measurement="%vol",
        suggested_display_precision=1,
        value_fn=lambda s: _recipe_value(s, "abv"),
    ),
    GrainfatherSessionSensorDescription(
        key="ibu",
        translation_key="session_ibu",
        native_unit_of_measurement="IBU",
        suggested_display_precision=0,
        value_fn=lambda s: _recipe_value(s, "ibu"),
    ),
    GrainfatherSessionSensorDescription(
        key="color_srm",
        translation_key="session_color_srm",
        native_unit_of_measurement="SRM",
        suggested_display_precision=1,
        value_fn=lambda s: _recipe_value(s, "srm"),
    ),
    GrainfatherSessionSensorDescription(
        key="calories",
        translation_key="session_calories",
        native_unit_of_measurement="kcal",
        suggested_display_precision=0,
        value_fn=lambda s: _recipe_value(s, "calories"),
    ),
    GrainfatherSessionSensorDescription(
        key="batch_size",
        translation_key="session_batch_size",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME,
        suggested_display_precision=1,
        value_fn=lambda s: _recipe_value(s, "batch_size"),
    ),
    GrainfatherSessionSensorDescription(
        key="boil_time",
        translation_key="session_boil_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        value_fn=lambda s: _recipe_value(s, "boil_time"),
    ),
    GrainfatherSessionSensorDescription(
        key="pre_boil_gravity",
        translation_key="session_pre_boil_gravity",
        suggested_display_precision=4,
        value_fn=lambda s: _raw_float(s, "pre_boil_gravity", "preBoilGravity"),
    ),
    GrainfatherSessionSensorDescription(
        key="pre_boil_gravity_plato",
        translation_key="session_pre_boil_gravity_plato",
        native_unit_of_measurement="°P",
        suggested_display_precision=1,
        value_fn=lambda s: sg_to_plato(
            _raw_float(s, "pre_boil_gravity", "preBoilGravity")
        ),
    ),
    GrainfatherSessionSensorDescription(
        key="conditioning_temperature",
        translation_key="session_conditioning_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        value_fn=lambda s: _raw_float(
            s, "conditioning_temperature", "conditioningTemperature"
        ),
    ),
    GrainfatherSessionSensorDescription(
        key="conditioning_duration",
        translation_key="session_conditioning_duration",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        value_fn=lambda s: _raw_float(
            s, "conditioning_duration", "conditioningDuration"
        ),
    ),
    GrainfatherSessionSensorDescription(
        key="ferment_volume",
        translation_key="session_ferment_volume",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME,
        suggested_display_precision=1,
        value_fn=lambda s: _raw_float(
            s,
            "ferment_volume_actual",
            "ferment_volume_est",
            "fermentVolumeActual",
            "fermentVolumeEst",
        ),
    ),
    GrainfatherSessionSensorDescription(
        key="priming_sugar",
        translation_key="session_priming_sugar",
        value_fn=lambda s: _raw_float(s, "priming_sugar_amount", "primingSugarAmount"),
        attributes_fn=lambda s, snapshot: _priming_sugar_attributes(s, snapshot),
    ),
    GrainfatherSessionSensorDescription(
        key="recipe_info",
        translation_key="session_recipe_info",
        value_fn=lambda s: (
            (s.recipe.name if s.recipe is not None else None) or s.recipe_name
        ),
        attributes_fn=lambda s, snapshot: _recipe_info_attributes(s, snapshot),
    ),
)


def _serialize_history_points(
    points: tuple[GrainfatherHistoryPoint, ...],
    max_points: int,
) -> list[dict[str, Any]]:
    # Keep attributes reasonably small for Home Assistant state storage.
    recent_points = points[-max_points:]
    return [
        {
            "timestamp": point.timestamp,
            "temperature": point.temperature,
            "specific_gravity": point.specific_gravity,
            "target_temperature": point.target_temperature,
        }
        for point in recent_points
    ]


def _truncate_text(value: str | None, max_chars: int) -> str | None:
    if value is None:
        return None
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars]}..."


def _last_history_value(
    points: tuple[GrainfatherHistoryPoint, ...],
    attr_name: str,
) -> float | None:
    for point in reversed(points):
        value = getattr(point, attr_name, None)
        if value is not None:
            return value
    return None


def _gravity_fallback(
    device: GrainfatherFermentationDevice,
    snapshot: GrainfatherSnapshot,
) -> float | None:
    """Fallback chain for gravity: linked session final_gravity → linked devices."""
    if device.last_specific_gravity is not None:
        return device.last_specific_gravity

    history = snapshot.fermentation_history_by_device_id.get(
        device.device_id or -1,
        tuple(),
    )
    history_gravity = _last_history_value(history, "specific_gravity")
    if history_gravity is not None:
        return history_gravity

    if device.linked_brew_session_id is not None:
        linked_session = next(
            (
                s
                for s in snapshot.brew_sessions
                if str(s.batch_id) == str(device.linked_brew_session_id)
            ),
            None,
        )
        if linked_session is not None and linked_session.final_gravity is not None:
            return linked_session.final_gravity

        other_device_gravity = next(
            (
                d.last_specific_gravity
                for d in snapshot.fermentation_devices
                if d.device_id != device.device_id
                and str(d.linked_brew_session_id) == str(device.linked_brew_session_id)
                and d.last_specific_gravity is not None
            ),
            None,
        )
        if other_device_gravity is not None:
            return other_device_gravity

    return None


def _get_collaborating_devices(
    device: GrainfatherFermentationDevice,
    snapshot: GrainfatherSnapshot,
) -> list[dict[str, Any]]:
    """Find other fermentation devices for the same session that provide data."""
    collaborators = []
    if device.linked_brew_session_id is None:
        return collaborators

    for other in snapshot.fermentation_devices:
        if other.device_id == device.device_id or str(
            other.linked_brew_session_id
        ) != str(device.linked_brew_session_id):
            continue

        has_data = (
            other.last_temperature is not None
            or other.last_specific_gravity is not None
        )
        if not has_data:
            history = snapshot.fermentation_history_by_device_id.get(
                other.device_id or -1,
                tuple(),
            )
            has_data = len(history) > 0

        if has_data:
            collaborators.append(
                {
                    "device_id": other.device_id,
                    "name": other.name or f"Fermentation Device {other.device_id}",
                }
            )

    return collaborators


def _session_batch_number_attributes(
    session: GrainfatherBrewSession,
    snapshot: GrainfatherSnapshot,
) -> dict[str, Any]:
    history: tuple[GrainfatherHistoryPoint, ...] = tuple()
    batch_id_int = None
    if session.batch_id is not None:
        try:
            batch_id_int = int(session.batch_id)
        except (TypeError, ValueError):
            batch_id_int = None

    if batch_id_int is not None:
        history = snapshot.brew_session_history_by_batch_id.get(batch_id_int, tuple())

    fermentation_devices = [
        {
            "device_id": device.device_id,
            "name": device.name or f"Fermentation Device {device.device_id}",
            "fermentation_device_type_id": device.fermentation_device_type_id,
        }
        for device in snapshot.fermentation_devices
        if str(device.linked_brew_session_id) == str(session.batch_id)
    ]

    return {
        "grainfather_entity_type": "brew_session",
        "batch_number": session.batch_number if session.batch_number is not None else 0,
        "batch_variant_name": session.batch_variant_name,
        "status": BREW_SESSION_STATUS_NAME_BY_CODE.get(session.status or -1, "unknown"),
        "is_current_batch": session.status == 20,
        "brew_session_id": session.batch_id,
        "recipe_id": session.recipe_id,
        "session_name": session.session_name,
        "recipe_name": session.recipe_name,
        "condition_date": session.condition_date,
        "fermentation_start_date": session.fermentation_start_date,
        "created_at": session.created_at,
        "recipe_image_url": session.recipe_image_url,
        "notes": _truncate_text(session.notes, _MAX_EXPOSED_NOTES_CHARS),
        "equipment_name": session.equipment_name,
        "fermentation_device_ids": list(session.fermentation_device_ids),
        "fermentation_devices": fermentation_devices,
        "fermentation_steps": [
            {
                "index": i,
                "name": step.name,
                "temperature": step.temperature,
                "duration_minutes": step.duration,
                "is_ramp_step": step.is_ramp_step,
            }
            for i, step in enumerate(session.fermentation_steps)
        ],
        "history_points": _serialize_history_points(
            history, _MAX_EXPOSED_BATCH_HISTORY_POINTS
        ),
        "history_points_count": len(history),
    }


def _session_device_info(session: GrainfatherBrewSession) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, brew_session_device_identifier(session))},
        name=brew_session_display_name(session),
        manufacturer="fidley",
        model="Brew Session",
        entry_type=DeviceEntryType.SERVICE,
    )


def _ferm_device_info(
    device: GrainfatherFermentationDevice,
    snapshot: GrainfatherSnapshot,
) -> DeviceInfo:
    kwargs: dict[str, Any] = {
        "identifiers": {(DOMAIN, f"fermdevice_{device.device_id}")},
        "name": device.name or f"Fermentation Device {device.device_id}",
        "manufacturer": "fidley",
        "model": "Fermentation Device",
        "entry_type": DeviceEntryType.SERVICE,
    }
    linked_session = next(
        (
            session
            for session in snapshot.brew_sessions
            if device.linked_brew_session_id is not None
            and str(session.batch_id) == str(device.linked_brew_session_id)
        ),
        None,
    )
    if linked_session is not None:
        kwargs["via_device"] = (DOMAIN, brew_session_device_identifier(linked_session))
    return DeviceInfo(**kwargs)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: GrainfatherDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_unique_ids: set[str] = set()

    entities = _build_sensor_entities(coordinator, entry, known_unique_ids)
    async_add_entities(entities)

    def _async_handle_coordinator_update() -> None:
        new_entities = _build_sensor_entities(coordinator, entry, known_unique_ids)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        coordinator.async_add_listener(_async_handle_coordinator_update)
    )


def _build_sensor_entities(
    coordinator: GrainfatherDataUpdateCoordinator,
    entry: ConfigEntry,
    known_unique_ids: set[str],
) -> list[SensorEntity]:
    entities: list[SensorEntity] = []

    for session in coordinator.data.brew_sessions:
        session_fragment = brew_session_unique_fragment(session)
        for description in SESSION_SENSORS:
            unique_id = f"{entry.entry_id}_session_{session_fragment}_{description.key}"
            if unique_id in known_unique_ids:
                continue
            known_unique_ids.add(unique_id)
            entities.append(
                GrainfatherSessionSensor(
                    coordinator,
                    entry,
                    session.batch_id,
                    session_fragment,
                    description,
                )
            )

    for device in coordinator.data.fermentation_devices:

        if device.device_id is None:
            continue
        active_charge_unique_id = (
            f"{entry.entry_id}_fermdevice_{device.device_id}_active_charge"
        )
        if active_charge_unique_id not in known_unique_ids:
            known_unique_ids.add(active_charge_unique_id)
            entities.append(
                GrainfatherFermDeviceActiveChargeSensor(
                    coordinator, entry, device.device_id
                )
            )

        temp_unique_id = f"{entry.entry_id}_fermdevice_{device.device_id}_temperature"
        if temp_unique_id not in known_unique_ids:
            known_unique_ids.add(temp_unique_id)
            entities.append(
                GrainfatherFermDeviceTemperatureSensor(
                    coordinator, entry, device.device_id
                )
            )

        gravity_unique_id = f"{entry.entry_id}_fermdevice_{device.device_id}_gravity"
        if gravity_unique_id not in known_unique_ids:
            known_unique_ids.add(gravity_unique_id)
            entities.append(
                GrainfatherFermDeviceGravitySensor(coordinator, entry, device.device_id)
            )
        plato_unique_id = (
            f"{entry.entry_id}_fermdevice_{device.device_id}_gravity_plato"
        )
        if plato_unique_id not in known_unique_ids:
            known_unique_ids.add(plato_unique_id)
            entities.append(
                GrainfatherFermDeviceGravityPlatoSensor(
                    coordinator, entry, device.device_id
                )
            )

        if device.fermentation_device_type_id == 30:
            target_temp_unique_id = (
                f"{entry.entry_id}_fermdevice_{device.device_id}_target_temperature"
            )
            if target_temp_unique_id not in known_unique_ids:
                known_unique_ids.add(target_temp_unique_id)
                entities.append(
                    GrainfatherFermDeviceTargetTemperatureSensor(
                        coordinator, entry, device.device_id
                    )
                )

    return entities


class GrainfatherSessionSensor(
    CoordinatorEntity[GrainfatherDataUpdateCoordinator],
    SensorEntity,
):
    entity_description: GrainfatherSessionSensorDescription

    def __init__(
        self,
        coordinator: GrainfatherDataUpdateCoordinator,
        entry: ConfigEntry,
        batch_id: int | str | None,
        session_unique_fragment: str,
        description: GrainfatherSessionSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._batch_id = batch_id
        self._attr_has_entity_name = True
        self._attr_unique_id = (
            f"{entry.entry_id}_session_{session_unique_fragment}_{description.key}"
        )

    @property
    def _session(self) -> GrainfatherBrewSession | None:
        for session in self.coordinator.data.brew_sessions:
            if str(session.batch_id) == str(self._batch_id):
                return session
        return None

    @property
    def available(self) -> bool:
        return self._session is not None

    @property
    def device_info(self) -> DeviceInfo | None:
        session = self._session
        if session is None:
            return None
        return _session_device_info(session)

    @property
    def native_value(self) -> Any:
        session = self._session
        if session is None:
            return None
        return self.entity_description.value_fn(session)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        session = self._session
        if session is None or self.entity_description.attributes_fn is None:
            return None
        attrs = self.entity_description.attributes_fn(session, self.coordinator.data)
        if attrs is None:
            return None
        if self.entity_description.key == "batch_number":
            try:
                batch_id = int(session.batch_id)
            except (TypeError, ValueError):
                pass
            else:
                attrs.update(
                    {
                        f"{metric}_statistic_id": batch_statistic_id(
                            self.coordinator.entry.entry_id, batch_id, metric
                        )
                        for metric in (
                            "temperature",
                            "specific_gravity",
                            "plato",
                        )
                    }
                )
        attrs["default_density_unit"] = self.coordinator.entry.options.get(
            CONF_DEFAULT_DENSITY_UNIT,
            DEFAULT_DENSITY_UNIT,
        )
        return attrs

    async def async_added_to_hass(self) -> None:
        """Write updated state whenever coordinator data changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._force_state_write_if_batch_number)
        )

    def _force_state_write_if_batch_number(self) -> None:
        """Force state write for the batch-number anchor sensor."""
        if self.entity_description.key == "batch_number":
            self.async_write_ha_state()

    @property
    def entity_picture(self) -> str | None:
        if self.entity_description.key != "recipe_image_url":
            return None
        session = self._session
        if session is None:
            return None
        return session.recipe_image_url


class GrainfatherFermDeviceActiveChargeSensor(
    CoordinatorEntity[GrainfatherDataUpdateCoordinator],
    SensorEntity,
):
    """Reference the fermenting brew session linked to a device."""

    _attr_translation_key = "fermdevice_active_charge"

    def __init__(
        self,
        coordinator: GrainfatherDataUpdateCoordinator,
        entry: ConfigEntry,
        device_id: int,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._entry_id = entry.entry_id
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{entry.entry_id}_fermdevice_{device_id}_active_charge"

    @property
    def _device(self) -> GrainfatherFermentationDevice | None:
        return next(
            (
                device
                for device in self.coordinator.data.fermentation_devices
                if device.device_id == self._device_id
            ),
            None,
        )

    @property
    def _session(self) -> GrainfatherBrewSession | None:
        device = self._device
        if device is None or device.linked_brew_session_id is None:
            return None
        return next(
            (
                session
                for session in self.coordinator.data.brew_sessions
                if str(session.batch_id) == str(device.linked_brew_session_id)
                and session.status == 20
            ),
            None,
        )

    @property
    def available(self) -> bool:
        return self._device is not None

    @property
    def native_value(self) -> str | None:
        session = self._session
        if session is None:
            return None
        return session.session_name or session.recipe_name

    @property
    def device_info(self) -> DeviceInfo | None:
        device = self._device
        if device is None:
            return None
        return _ferm_device_info(device, self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        session = self._session
        if session is None:
            return None
        session_unique_id = (
            f"{self._entry_id}_session_{brew_session_unique_fragment(session)}_batch_number"
        )
        attrs: dict[str, Any] = {
            "grainfather_entity_type": "fermentation_device_active_charge",
            "brew_session_id": session.batch_id,
            "brew_session_unique_id": session_unique_id,
            "status": BREW_SESSION_STATUS_NAME_BY_CODE.get(
                session.status or -1, "unknown"
            ),
            "is_current_batch": True,
        }
        hass = getattr(self, "hass", None)
        if hass is not None:
            entity_id = er.async_get(hass).async_get_entity_id(
                "sensor", DOMAIN, session_unique_id
            )
            if entity_id is not None:
                attrs["brew_session_entity_id"] = entity_id
        return attrs


class GrainfatherFermDeviceTemperatureSensor(
    CoordinatorEntity[GrainfatherDataUpdateCoordinator],
    SensorEntity,
):
    _attr_translation_key = "fermdevice_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: GrainfatherDataUpdateCoordinator,
        entry: ConfigEntry,
        device_id: int | None,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{entry.entry_id}_fermdevice_{device_id}_temperature"

    @property
    def _device(self) -> GrainfatherFermentationDevice | None:
        for device in self.coordinator.data.fermentation_devices:
            if device.device_id == self._device_id:
                return device
        return None

    @property
    def available(self) -> bool:
        return self._device is not None

    @property
    def native_value(self) -> Any:
        device = self._device
        if device is None:
            return None
        if device.last_temperature is not None:
            return device.last_temperature
        history = self.coordinator.data.fermentation_history_by_device_id.get(
            device.device_id or -1,
            tuple(),
        )
        return _last_history_value(history, "temperature")

    @property
    def device_info(self) -> DeviceInfo | None:
        device = self._device
        if device is None:
            return None
        return _ferm_device_info(device, self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        device = self._device
        if device is None:
            return None
        history = self.coordinator.data.fermentation_history_by_device_id.get(
            device.device_id or -1,
            tuple(),
        )
        collaborators = _get_collaborating_devices(device, self.coordinator.data)
        return {
            "grainfather_entity_type": "fermentation_device",
            "device_id": device.device_id,
            "last_heard": device.last_heard,
            "last_specific_gravity": device.last_specific_gravity,
            "linked_brew_session_id": device.linked_brew_session_id,
            "linked_brew_session_name": device.linked_brew_session_name,
            "is_controller_linked": device.is_controller_linked,
            "collaborating_devices": collaborators,
            "default_density_unit": self.coordinator.entry.options.get(
                CONF_DEFAULT_DENSITY_UNIT,
                DEFAULT_DENSITY_UNIT,
            ),
            "history_points": _serialize_history_points(
                history, _MAX_EXPOSED_DEVICE_HISTORY_POINTS
            ),
            "history_points_count": len(history),
        }


class GrainfatherFermDeviceGravitySensor(
    CoordinatorEntity[GrainfatherDataUpdateCoordinator],
    SensorEntity,
):
    _attr_translation_key = "fermdevice_gravity"
    _attr_suggested_display_precision = 4

    def __init__(
        self,
        coordinator: GrainfatherDataUpdateCoordinator,
        entry: ConfigEntry,
        device_id: int | None,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{entry.entry_id}_fermdevice_{device_id}_gravity"

    @property
    def _device(self) -> GrainfatherFermentationDevice | None:
        for device in self.coordinator.data.fermentation_devices:
            if device.device_id == self._device_id:
                return device
        return None

    @property
    def available(self) -> bool:
        return self._device is not None

    @property
    def native_value(self) -> Any:
        device = self._device
        if device is None:
            return None
        return _gravity_fallback(device, self.coordinator.data)

    @property
    def device_info(self) -> DeviceInfo | None:
        device = self._device
        if device is None:
            return None
        return _ferm_device_info(device, self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        device = self._device
        if device is None:
            return None
        history = self.coordinator.data.fermentation_history_by_device_id.get(
            device.device_id or -1,
            tuple(),
        )
        collaborators = _get_collaborating_devices(device, self.coordinator.data)
        return {
            "device_id": device.device_id,
            "last_heard": device.last_heard,
            "linked_brew_session_id": device.linked_brew_session_id,
            "linked_brew_session_name": device.linked_brew_session_name,
            "collaborating_devices": collaborators,
            "default_density_unit": self.coordinator.entry.options.get(
                CONF_DEFAULT_DENSITY_UNIT,
                DEFAULT_DENSITY_UNIT,
            ),
            "history_points": _serialize_history_points(
                history, _MAX_EXPOSED_DEVICE_HISTORY_POINTS
            ),
            "history_points_count": len(history),
        }


class GrainfatherFermDeviceGravityPlatoSensor(GrainfatherFermDeviceGravitySensor):
    _attr_translation_key = "fermdevice_gravity_plato"
    _attr_native_unit_of_measurement = "°P"
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: GrainfatherDataUpdateCoordinator,
        entry: ConfigEntry,
        device_id: int | None,
    ) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{entry.entry_id}_fermdevice_{device_id}_gravity_plato"

    @property
    def native_value(self) -> Any:
        return sg_to_plato(super().native_value)


class GrainfatherFermDeviceTargetTemperatureSensor(
    CoordinatorEntity[GrainfatherDataUpdateCoordinator],
    SensorEntity,
):
    _attr_translation_key = "fermdevice_target_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: GrainfatherDataUpdateCoordinator,
        entry: ConfigEntry,
        device_id: int | None,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_has_entity_name = True
        self._attr_unique_id = (
            f"{entry.entry_id}_fermdevice_{device_id}_target_temperature"
        )

    @property
    def _device(self) -> GrainfatherFermentationDevice | None:
        for device in self.coordinator.data.fermentation_devices:
            if device.device_id == self._device_id:
                return device
        return None

    @property
    def available(self) -> bool:
        return self._device is not None

    @property
    def native_value(self) -> Any:
        device = self._device
        if device is None:
            return None
        history = self.coordinator.data.fermentation_history_by_device_id.get(
            device.device_id or -1,
            tuple(),
        )
        return _last_history_value(history, "target_temperature")

    @property
    def device_info(self) -> DeviceInfo | None:
        device = self._device
        if device is None:
            return None
        return _ferm_device_info(device, self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        device = self._device
        if device is None:
            return None
        return {
            "grainfather_entity_type": "fermentation_device",
            "device_id": device.device_id,
            "last_heard": device.last_heard,
            "linked_brew_session_id": device.linked_brew_session_id,
            "linked_brew_session_name": device.linked_brew_session_name,
        }
