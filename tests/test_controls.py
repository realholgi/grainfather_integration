from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.grainfather.api import (
    GrainfatherAccount,
    GrainfatherSnapshot,
    brew_session_unique_fragment,
    parse_batch_payload,
)
from custom_components.grainfather.number import (
    GrainfatherFermentationStepDurationNumber,
    GrainfatherFermentationStepFinishTemperatureNumber,
    GrainfatherFermentationStepTemperatureNumber,
)
from custom_components.grainfather.select import (
    GrainfatherFermentationStepRampSelect,
    GrainfatherSessionStatusSelect,
)


class _Coordinator:
    def __init__(self, snapshot) -> None:
        self.data = snapshot
        self.api = SimpleNamespace(
            async_set_brew_session_status=AsyncMock(),
            async_set_fermentation_step_duration=AsyncMock(),
        )
        self.note_user_action = MagicMock()

    def async_add_listener(self, callback, context=None):
        del callback, context
        return lambda: None


def _coordinator() -> tuple[_Coordinator, SimpleNamespace, str]:
    session = parse_batch_payload(
        {
            "id": 1001,
            "recipe_id": 700,
            "batch_number": 42,
            "session_name": "Control Test Batch",
            "status": 20,
            "fermentation_steps": [
                {
                    "id": 11,
                    "name": "Primary",
                    "temperature": 20.0,
                    "time": 120,
                    "is_ramp_step": False,
                    "finish_temperature": 21.0,
                }
            ],
        }
    )
    assert session is not None
    coordinator = _Coordinator(
        GrainfatherSnapshot(
            account=GrainfatherAccount(None, None, None, None),
            brew_sessions=(session,),
            fermentation_devices=(),
        )
    )
    return (
        coordinator,
        SimpleNamespace(entry_id="test-entry"),
        brew_session_unique_fragment(session),
    )


async def test_number_entities_report_values_and_dispatch_updates() -> None:
    """Step number controls convert Home Assistant values into API mutations."""
    coordinator, entry, fragment = _coordinator()
    duration = GrainfatherFermentationStepDurationNumber(
        coordinator, entry, 1001, fragment, 0
    )
    temperature = GrainfatherFermentationStepTemperatureNumber(
        coordinator, entry, 1001, fragment, 0
    )
    finish_temperature = GrainfatherFermentationStepFinishTemperatureNumber(
        coordinator, entry, 1001, fragment, 0
    )

    assert duration.available is True
    assert duration.native_value == 2.0
    assert temperature.native_value == 20.0
    assert finish_temperature.native_value == 21.0

    await duration.async_set_native_value(1.5)
    await temperature.async_set_native_value(19.25)
    await finish_temperature.async_set_native_value(18.5)

    assert coordinator.api.async_set_fermentation_step_duration.await_args_list == [
        call(700, 1001, 0, 90),
        call(700, 1001, 0, temperature=19.25),
        call(700, 1001, 0, finish_temperature=18.5, set_finish_temperature=True),
    ]
    assert coordinator.note_user_action.call_count == 3


async def test_select_entities_dispatch_supported_options() -> None:
    """Status and ramp selects normalize UI values before calling the API."""
    coordinator, entry, fragment = _coordinator()
    status = GrainfatherSessionStatusSelect(coordinator, entry, 1001, fragment)
    ramp = GrainfatherFermentationStepRampSelect(coordinator, entry, 1001, fragment, 0)

    assert status.current_option == "fermenting"
    assert ramp.current_option == "off"

    await status.async_select_option("conditioning")
    await ramp.async_select_option("on")

    coordinator.api.async_set_brew_session_status.assert_awaited_once_with(
        700, 1001, 30
    )
    coordinator.api.async_set_fermentation_step_duration.assert_awaited_once_with(
        700, 1001, 0, is_ramp_step=True
    )
    assert coordinator.note_user_action.call_count == 2

    with pytest.raises(HomeAssistantError, match="Unsupported ramp step option"):
        await ramp.async_select_option("invalid")
