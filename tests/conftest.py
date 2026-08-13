import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from homeassistant import loader

import custom_components
import custom_components.grainfather as grainfather

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Setuptools' editable finder adds a non-filesystem namespace path that Home
# Assistant's custom-component loader cannot scan.
custom_components.__path__ = [str(ROOT / "custom_components")]


@pytest.fixture(autouse=True)
async def disable_peripheral_integration_dependencies(hass, monkeypatch):
    """Avoid starting frontend, static resources, and Recorder in unit tests."""
    integration = await loader.async_get_integration(hass, "grainfather")
    integration.manifest["dependencies"] = []
    integration.__dict__.pop("dependencies", None)
    integration._all_dependencies = set()
    monkeypatch.setattr(grainfather, "_async_register_card_resources", AsyncMock())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
