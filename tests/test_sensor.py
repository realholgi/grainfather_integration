from types import SimpleNamespace

from custom_components.grainfather.api import (
    GrainfatherAccount,
    GrainfatherFermentationDevice,
    GrainfatherSnapshot,
    brew_session_unique_fragment,
    parse_batch_payload,
)
from custom_components.grainfather.sensor import (
    SESSION_SENSORS,
    _build_sensor_entities,
)


def _session(batch_id: int, *, status: int = 20):
    session = parse_batch_payload(
        {
            "id": batch_id,
            "batch_number": batch_id - 1000,
            "name": f"Recipe {batch_id}",
            "session_name": f"Session {batch_id}",
            "status": status,
            "fermentation_start_date": "2026-08-06T14:00:00Z",
        }
    )
    assert session is not None
    return session


def _device(
    device_id: int,
    batch_id: int | None,
    *,
    name: str | None = None,
    device_type: int | None = None,
    temperature: float | None = 20.0,
    gravity: float | None = None,
) -> GrainfatherFermentationDevice:
    return GrainfatherFermentationDevice(
        device_id=device_id,
        name=name or f"Device {device_id}",
        fermentation_device_type_id=device_type,
        linked_brew_session_id=batch_id,
        linked_brew_session_name=None,
        last_heard=None,
        last_specific_gravity=gravity,
        last_temperature=temperature,
        is_controller_linked=None,
        raw_payload={},
    )


def _snapshot(
    devices: tuple[GrainfatherFermentationDevice, ...], sessions=()
) -> GrainfatherSnapshot:
    return GrainfatherSnapshot(
        account=GrainfatherAccount(None, None, None, None),
        brew_sessions=tuple(sessions),
        fermentation_devices=devices,
        fermentation_history_by_device_id={},
    )


def _entities(coordinator):
    entry = SimpleNamespace(entry_id="test-entry", options={})
    coordinator.entry = entry
    return _build_sensor_entities(coordinator, entry, set())


def _batch_number(entities, batch_id: int):
    fragment = brew_session_unique_fragment(_session(batch_id))
    return next(
        entity
        for entity in entities
        if entity.unique_id == f"test-entry_session_{fragment}_batch_number"
    )


def test_fermenting_session_is_the_canonical_current_batch_anchor() -> None:
    batch_id = 1001
    controller = _device(
        1, batch_id, name="Keller Holgi 1", device_type=30, gravity=None
    )
    tilt = _device(2, batch_id, name="Keller Red Tilt", gravity=1.050)
    coordinator = SimpleNamespace(
        data=_snapshot((controller, tilt), (_session(batch_id),)),
        last_update_success=True,
    )

    entities = _entities(coordinator)
    unique_ids = {entity.unique_id for entity in entities}
    assert not any("_current_batch" in unique_id for unique_id in unique_ids)
    session_fragment = brew_session_unique_fragment(_session(batch_id))
    session_ids = {
        unique_id
        for unique_id in unique_ids
        if f"_session_{session_fragment}_" in unique_id
    }
    assert len(session_ids) == len(SESSION_SENSORS)
    assert {unique_id for unique_id in unique_ids if "_fermdevice_1_" in unique_id} == {
        "test-entry_fermdevice_1_active_charge",
        "test-entry_fermdevice_1_temperature",
        "test-entry_fermdevice_1_gravity",
        "test-entry_fermdevice_1_gravity_plato",
        "test-entry_fermdevice_1_target_temperature",
    }
    assert {unique_id for unique_id in unique_ids if "_fermdevice_2_" in unique_id} == {
        "test-entry_fermdevice_2_active_charge",
        "test-entry_fermdevice_2_temperature",
        "test-entry_fermdevice_2_gravity",
        "test-entry_fermdevice_2_gravity_plato",
    }

    active_charge = next(
        entity
        for entity in entities
        if entity.unique_id == "test-entry_fermdevice_1_active_charge"
    )
    assert active_charge.native_value == "Session 1001"
    assert active_charge.extra_state_attributes == {
        "grainfather_entity_type": "fermentation_device_active_charge",
        "brew_session_id": 1001,
        "brew_session_unique_id": (
            "test-entry_session_id_1001_no_1_batch_number"
        ),
        "status": "fermenting",
        "is_current_batch": True,
    }

    attrs = _batch_number(entities, batch_id).extra_state_attributes
    assert attrs is not None
    assert attrs["is_current_batch"] is True
    assert attrs["fermentation_devices"] == [
        {"device_id": 1, "name": "Keller Holgi 1", "fermentation_device_type_id": 30},
        {
            "device_id": 2,
            "name": "Keller Red Tilt",
            "fermentation_device_type_id": None,
        },
    ]
    assert {
        key: attrs[key]
        for key in (
            "temperature_statistic_id",
            "specific_gravity_statistic_id",
            "plato_statistic_id",
        )
    } == {
        "temperature_statistic_id": "grainfather:test_entry_batch_1001_temperature",
        "specific_gravity_statistic_id": (
            "grainfather:test_entry_batch_1001_specific_gravity"
        ),
        "plato_statistic_id": "grainfather:test_entry_batch_1001_plato",
    }

    coordinator.data = _snapshot((controller, tilt), (_session(batch_id, status=30),))
    assert (
        _batch_number(entities, batch_id).extra_state_attributes["is_current_batch"]
        is False
    )
    assert {entity.unique_id for entity in entities} == unique_ids
    assert active_charge.native_value is None
    assert active_charge.extra_state_attributes is None


def test_simultaneous_fermenting_sessions_keep_device_links_separate() -> None:
    batch_a, batch_b = 1001, 1002
    coordinator = SimpleNamespace(
        data=_snapshot(
            (
                _device(1, batch_a, name="Keller Holgi 1"),
                _device(2, batch_b, name="Keller Red Tilt"),
            ),
            (_session(batch_a), _session(batch_b)),
        ),
        last_update_success=True,
    )
    entities = _entities(coordinator)

    attrs_a = _batch_number(entities, batch_a).extra_state_attributes
    attrs_b = _batch_number(entities, batch_b).extra_state_attributes
    assert attrs_a["fermentation_devices"] == [
        {"device_id": 1, "name": "Keller Holgi 1", "fermentation_device_type_id": None}
    ]
    assert attrs_b["fermentation_devices"] == [
        {"device_id": 2, "name": "Keller Red Tilt", "fermentation_device_type_id": None}
    ]
    assert attrs_a["temperature_statistic_id"].endswith("batch_1001_temperature")
    assert attrs_b["temperature_statistic_id"].endswith("batch_1002_temperature")


def test_active_charge_references_only_its_linked_fermenting_session() -> None:
    batch_a, batch_b = 1001, 1002
    coordinator = SimpleNamespace(
        data=_snapshot(
            (
                _device(1, batch_a, name="Keller Holgi 1"),
                _device(2, batch_b, name="Keller Red Tilt"),
                _device(3, None, name="Unlinked"),
            ),
            (_session(batch_a), _session(batch_b, status=30)),
        ),
        last_update_success=True,
    )
    entities = _entities(coordinator)

    active_charges = {
        entity.unique_id: entity
        for entity in entities
        if entity.unique_id.endswith("_active_charge")
    }
    assert active_charges["test-entry_fermdevice_1_active_charge"].native_value == (
        "Session 1001"
    )
    assert (
        active_charges["test-entry_fermdevice_2_active_charge"].native_value is None
    )
    assert (
        active_charges["test-entry_fermdevice_3_active_charge"].native_value is None
    )

