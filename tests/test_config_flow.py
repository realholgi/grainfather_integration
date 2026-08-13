from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.grainfather.api import (
    GrainfatherApiError,
    GrainfatherAuthenticationError,
)
from custom_components.grainfather.const import (
    CONF_ACTIVE_SCAN_INTERVAL,
    CONF_DEFAULT_DENSITY_UNIT,
    CONF_EMAIL,
    CONF_INCLUDE_COMPLETED_SESSIONS,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    DEFAULT_ACTIVE_SCAN_INTERVAL,
    DEFAULT_DENSITY_UNIT,
    DEFAULT_INCLUDE_COMPLETED_SESSIONS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


async def test_user_flow_creates_entry(hass) -> None:
    """The flow validates submitted credentials and preserves the account title."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(
        "custom_components.grainfather.config_flow."
        "GrainfatherApiClient.async_validate_credentials",
        new_callable=AsyncMock,
    ) as validate_credentials:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_EMAIL: "Brewer@Example.com",
                CONF_PASSWORD: "test-password",
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Brewer@Example.com"
    assert result["data"] == {
        CONF_EMAIL: "Brewer@Example.com",
        CONF_PASSWORD: "test-password",
    }
    assert result["result"].unique_id == "brewer@example.com"
    validate_credentials.assert_awaited_once()


@pytest.mark.parametrize(
    ("error", "expected_error"),
    [
        (GrainfatherAuthenticationError("invalid credentials"), "invalid_auth"),
        (GrainfatherApiError("unreachable"), "cannot_connect"),
    ],
)
async def test_user_flow_returns_validation_error(hass, error, expected_error) -> None:
    """Credential failures stay in the form and do not create an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )

    with patch(
        "custom_components.grainfather.config_flow."
        "GrainfatherApiClient.async_validate_credentials",
        new_callable=AsyncMock,
        side_effect=error,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_EMAIL: "Brewer@Example.com",
                CONF_PASSWORD: "test-password",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": expected_error}


async def test_user_flow_rejects_duplicate_before_validation(hass) -> None:
    """A case-insensitive duplicate must not issue an API request."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="brewer@example.com",
        data={CONF_EMAIL: "Brewer@Example.com", CONF_PASSWORD: "test-password"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )

    with patch(
        "custom_components.grainfather.config_flow."
        "GrainfatherApiClient.async_validate_credentials",
        new_callable=AsyncMock,
    ) as validate_credentials:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_EMAIL: "BREWER@example.com",
                CONF_PASSWORD: "test-password",
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    validate_credentials.assert_not_awaited()


async def test_options_flow_exposes_defaults_and_saves_valid_options(hass) -> None:
    """Options use integration defaults and persist submitted values."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_EMAIL: "Brewer@Example.com", CONF_PASSWORD: "test-password"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["data_schema"]({}) == {
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_ACTIVE_SCAN_INTERVAL: DEFAULT_ACTIVE_SCAN_INTERVAL,
        CONF_INCLUDE_COMPLETED_SESSIONS: DEFAULT_INCLUDE_COMPLETED_SESSIONS,
        CONF_DEFAULT_DENSITY_UNIT: DEFAULT_DENSITY_UNIT,
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SCAN_INTERVAL: 600,
            CONF_ACTIVE_SCAN_INTERVAL: 120,
            CONF_INCLUDE_COMPLETED_SESSIONS: True,
            CONF_DEFAULT_DENSITY_UNIT: "plato",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_SCAN_INTERVAL: 600,
        CONF_ACTIVE_SCAN_INTERVAL: 120,
        CONF_INCLUDE_COMPLETED_SESSIONS: True,
        CONF_DEFAULT_DENSITY_UNIT: "plato",
    }
