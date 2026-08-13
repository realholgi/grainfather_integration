from unittest.mock import AsyncMock, call, patch

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.grainfather.api import (
    GrainfatherAccount,
    GrainfatherSnapshot,
    brew_session_device_identifier,
    brew_session_unique_fragment,
    parse_batch_payload,
    parse_fermentation_device_payload,
)
from custom_components.grainfather.const import (
    CONF_BREW_SESSION_ID,
    CONF_DURATION_MINUTES,
    CONF_EMAIL,
    CONF_ENTRY_ID,
    CONF_FERMENTATION_STEPS,
    CONF_FINISH_TEMPERATURE,
    CONF_IS_RAMP_STEP,
    CONF_PASSWORD,
    CONF_STATUS,
    CONF_STEP_INDEX,
    CONF_TEMPERATURE,
    DOMAIN,
    SERVICE_ADJUST_CURRENT_STEP_DURATION,
    SERVICE_ADJUST_CURRENT_STEP_TEMPERATURE,
    SERVICE_ADVANCE_TO_NEXT_FERMENTATION_STEP,
    SERVICE_CLEAR_FERMENTATION_STEP_FINISH_TEMPERATURE,
    SERVICE_SET_BREW_SESSION_STATUS,
    SERVICE_SET_FERMENTATION_STEP_DURATION,
    SERVICE_SET_FERMENTATION_STEPS,
)

_ALL_SERVICES = (
    SERVICE_ADJUST_CURRENT_STEP_TEMPERATURE,
    SERVICE_ADJUST_CURRENT_STEP_DURATION,
    SERVICE_ADVANCE_TO_NEXT_FERMENTATION_STEP,
    SERVICE_SET_BREW_SESSION_STATUS,
    SERVICE_SET_FERMENTATION_STEPS,
    SERVICE_SET_FERMENTATION_STEP_DURATION,
    SERVICE_CLEAR_FERMENTATION_STEP_FINISH_TEMPERATURE,
)


def _snapshot(
    *,
    status: int = 20,
    controller_temperature: float = 20.4,
    hydrometer=False,
    second_step=False,
):
    fermentation_steps = [
        {
            "id": 11,
            "name": "Primary",
            "temperature": 20.0,
            "time": 120,
            "order": 1,
            "time_unit_id": 2,
            "is_ramp_step": False,
            "finish_temperature": 21.0,
        }
    ]
    if second_step:
        fermentation_steps[0]["time"] = 999999
        fermentation_steps.append(
            {
                "id": 12,
                "name": "Conditioning",
                "temperature": 18.0,
                "time": 60,
                "order": 2,
                "time_unit_id": 2,
                "is_ramp_step": False,
                "finish_temperature": None,
            }
        )

    session = parse_batch_payload(
        {
            "id": 1001,
            "recipe_id": 700,
            "batch_number": 42,
            "name": "Runtime Test Recipe",
            "session_name": "Runtime Test Batch",
            "status": status,
            "fermentation_start_date": "2026-08-06T14:00:00Z",
            "fermentation_devices": [30],
            "fermentation_steps": fermentation_steps,
        }
    )
    assert session is not None
    devices = [
        parse_fermentation_device_payload(
            {
                "id": 30,
                "name": "Runtime Controller",
                "fermentation_device_type_id": 30,
                "brew_session_id": 1001,
                "last_temperature": controller_temperature,
            }
        )
    ]
    if hydrometer:
        devices.append(
            parse_fermentation_device_payload(
                {
                    "id": 10,
                    "name": "Runtime Hydrometer",
                    "fermentation_device_type_id": 10,
                    "brew_session_id": 1001,
                    "last_temperature": 19.1,
                    "last_sg": 1.012,
                }
            )
        )
    return GrainfatherSnapshot(
        account=GrainfatherAccount(None, None, None, None),
        brew_sessions=(session,),
        fermentation_devices=tuple(devices),
        fermentation_history_by_device_id={},
    )


def _entity_id(hass, platform: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id


async def _setup_entry(hass, snapshot):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="brewer@example.com",
        data={CONF_EMAIL: "Brewer@Example.com", CONF_PASSWORD: "test-password"},
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.grainfather.api.GrainfatherApiClient.async_get_snapshot",
            new_callable=AsyncMock,
            return_value=snapshot,
        ),
        patch(
            "custom_components.grainfather."
            "GrainfatherHistoryImporter.async_import_full_history",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.grainfather._async_register_card_resources",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.grainfather._async_create_helpers",
            new_callable=AsyncMock,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_config_entry_runtime_registers_and_updates_entities(hass) -> None:
    """Real platform forwarding exposes state, topology, and dynamic devices."""
    first_snapshot = _snapshot()
    entry = await _setup_entry(hass, first_snapshot)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    fragment = brew_session_unique_fragment(first_snapshot.brew_sessions[0])

    assert entry.state.name == "LOADED"
    assert all(hass.services.has_service(DOMAIN, service) for service in _ALL_SERVICES)

    batch_number = _entity_id(
        hass, "sensor", f"{entry.entry_id}_session_{fragment}_batch_number"
    )
    controller_temperature = _entity_id(
        hass, "sensor", f"{entry.entry_id}_fermdevice_30_temperature"
    )
    active_charge = _entity_id(
        hass, "sensor", f"{entry.entry_id}_fermdevice_30_active_charge"
    )
    _entity_id(hass, "sensor", f"{entry.entry_id}_fermdevice_30_target_temperature")
    status = _entity_id(
        hass, "select", f"{entry.entry_id}_session_{fragment}_status_select"
    )
    ramp = _entity_id(
        hass, "select", f"{entry.entry_id}_session_{fragment}_step_0_ramp_select"
    )
    duration = _entity_id(
        hass, "number", f"{entry.entry_id}_session_{fragment}_step_0_duration"
    )
    temperature = _entity_id(
        hass, "number", f"{entry.entry_id}_session_{fragment}_step_0_temperature"
    )
    finish_temperature = _entity_id(
        hass, "number", f"{entry.entry_id}_session_{fragment}_step_0_finish_temperature"
    )

    batch_number_state = hass.states.get(batch_number)
    assert batch_number_state is not None
    assert batch_number_state.state == "42"
    assert batch_number_state.attributes["is_current_batch"] is True
    assert batch_number_state.attributes["temperature_statistic_id"].endswith(
        "batch_1001_temperature"
    )
    assert hass.states.get(controller_temperature).state == "20.4"
    assert hass.states.get(active_charge).state == "Runtime Test Batch"
    assert hass.states.get(status).state == "fermenting"
    assert hass.states.get(ramp).state == "off"
    assert hass.states.get(duration).state == "2.0"
    assert hass.states.get(temperature).state == "20.0"
    assert hass.states.get(finish_temperature).state == "21.0"

    device_registry = dr.async_get(hass)
    batch_device = device_registry.async_get_device(
        identifiers={
            (DOMAIN, brew_session_device_identifier(first_snapshot.brew_sessions[0]))
        }
    )
    controller_device = device_registry.async_get_device(
        identifiers={(DOMAIN, "fermdevice_30")}
    )
    assert batch_device is not None
    assert controller_device is not None
    assert controller_device.via_device_id == batch_device.id

    coordinator.async_set_updated_data(
        _snapshot(status=30, controller_temperature=18.7, hydrometer=True)
    )
    await hass.async_block_till_done()

    assert hass.states.get(batch_number).attributes["is_current_batch"] is False
    assert hass.states.get(active_charge).state == STATE_UNKNOWN
    assert hass.states.get(controller_temperature).state == "18.7"
    assert (
        hass.states.get(
            _entity_id(hass, "sensor", f"{entry.entry_id}_fermdevice_10_temperature")
        ).state
        == "19.1"
    )
    assert (
        hass.states.get(
            _entity_id(hass, "sensor", f"{entry.entry_id}_fermdevice_10_gravity")
        ).state
        == "1.012"
    )
    assert (
        hass.states.get(
            _entity_id(hass, "sensor", f"{entry.entry_id}_fermdevice_10_gravity_plato")
        ).state
        == "3.1"
    )


async def test_setup_prunes_target_records_dispatches_service_and_unloads(hass) -> None:
    """Runtime lifecycle removes only stale target records and unregisters cleanly."""
    snapshot = _snapshot()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="brewer@example.com",
        data={CONF_EMAIL: "Brewer@Example.com", CONF_PASSWORD: "test-password"},
    )
    other_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="other@example.com",
        disabled_by=ConfigEntryDisabler.USER,
    )
    entry.add_to_hass(hass)

    other_entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    stale_session = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_session_id_999_no_1_batch_number",
        config_entry=entry,
    )
    stale_device = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_fermdevice_999_temperature",
        config_entry=entry,
    )
    legacy_image = entity_registry.async_get_or_create(
        "image", DOMAIN, "legacy-image", config_entry=entry
    )
    other_entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{other_entry.entry_id}_session_id_999_no_1_batch_number",
        config_entry=other_entry,
    )
    device_registry = dr.async_get(hass)
    stale_device_record = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "fermdevice_999")}
    )

    with (
        patch(
            "custom_components.grainfather.api.GrainfatherApiClient.async_get_snapshot",
            new_callable=AsyncMock,
            return_value=snapshot,
        ),
        patch(
            "custom_components.grainfather."
            "GrainfatherHistoryImporter.async_import_full_history",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.grainfather._async_register_card_resources",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.grainfather._async_create_helpers",
            new_callable=AsyncMock,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entity_registry.async_get(stale_session.entity_id) is None
    assert entity_registry.async_get(stale_device.entity_id) is None
    assert entity_registry.async_get(legacy_image.entity_id) is None
    assert entity_registry.async_get(other_entity.entity_id) is not None
    assert device_registry.async_get(stale_device_record.id) is None

    coordinator = hass.data[DOMAIN][entry.entry_id]
    with (
        patch.object(
            coordinator.api, "async_set_brew_session_status", new_callable=AsyncMock
        ) as set_status,
        patch.object(
            coordinator, "async_request_refresh", new_callable=AsyncMock
        ) as request_refresh,
    ):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_BREW_SESSION_STATUS,
            {
                CONF_ENTRY_ID: entry.entry_id,
                CONF_BREW_SESSION_ID: 1001,
                CONF_STATUS: "conditioning",
            },
            blocking=True,
        )
        await hass.async_block_till_done()
    set_status.assert_awaited_once_with(700, 1001, 30)
    request_refresh.assert_awaited_once()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert (
        hass.states.get(
            _entity_id(
                hass,
                "sensor",
                f"{entry.entry_id}_session_id_1001_no_42_batch_number",
            )
        ).state
        == STATE_UNAVAILABLE
    )
    assert entry.entry_id not in hass.data[DOMAIN]
    assert not any(
        hass.services.has_service(DOMAIN, service) for service in _ALL_SERVICES
    )


async def test_services_dispatch_all_fermentation_mutations(hass) -> None:
    """Services validate payloads and route every fermentation mutation to its API."""
    entry = await _setup_entry(hass, _snapshot(second_step=True))
    coordinator = hass.data[DOMAIN][entry.entry_id]
    target = {CONF_ENTRY_ID: entry.entry_id, CONF_BREW_SESSION_ID: 1001}
    steps = [{"name": "Updated", "temperature": 19.5, "time": 90}]

    with (
        patch.object(
            coordinator.api,
            "async_set_fermentation_step_duration",
            new_callable=AsyncMock,
        ) as update_step,
        patch.object(
            coordinator.api,
            "async_set_fermentation_steps",
            new_callable=AsyncMock,
        ) as update_steps,
        patch.object(coordinator, "note_user_action") as note_user_action,
    ):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADJUST_CURRENT_STEP_TEMPERATURE,
            {**target, CONF_TEMPERATURE: 20.126},
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADJUST_CURRENT_STEP_DURATION,
            {**target, CONF_DURATION_MINUTES: 0},
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADVANCE_TO_NEXT_FERMENTATION_STEP,
            target,
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_FERMENTATION_STEPS,
            {**target, CONF_FERMENTATION_STEPS: steps},
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_FERMENTATION_STEP_DURATION,
            {
                **target,
                CONF_STEP_INDEX: 1,
                CONF_DURATION_MINUTES: 55,
                CONF_TEMPERATURE: 17.6,
                CONF_IS_RAMP_STEP: True,
                CONF_FINISH_TEMPERATURE: 18.0,
            },
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEAR_FERMENTATION_STEP_FINISH_TEMPERATURE,
            {**target, CONF_STEP_INDEX: 1},
            blocking=True,
        )

    assert update_step.await_args_list[:2] == [
        call(700, 1001, 0, temperature=20.13),
        call(700, 1001, 0, duration_minutes=1),
    ]
    advance_call = update_step.await_args_list[2]
    assert advance_call.args == (700, 1001, 0)
    assert advance_call.kwargs["duration_minutes"] > 0
    assert update_step.await_args_list[3:] == [
        call(
            700,
            1001,
            1,
            55,
            temperature=17.6,
            is_ramp_step=True,
            finish_temperature=18.0,
            set_finish_temperature=True,
        ),
        call(700, 1001, 1, finish_temperature=None, set_finish_temperature=True),
    ]
    update_steps.assert_awaited_once_with(700, 1001, steps)
    assert note_user_action.call_count == 6
