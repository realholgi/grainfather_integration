from types import SimpleNamespace
from typing import Any

from custom_components.grainfather.api import (
    GrainfatherAccount,
    GrainfatherSnapshot,
    parse_batch_payload,
)
from custom_components.grainfather.const import DOMAIN
from custom_components.grainfather.image import (
    GrainfatherIntegrationIconImage,
    GrainfatherSessionRecipeImage,
    async_setup_entry,
)


class _Coordinator:
    def __init__(self, snapshot) -> None:
        self.data = snapshot

    def async_add_listener(self, callback, context=None):
        del callback, context
        return lambda: None


def _session(*, image_url: str | None):
    session = parse_batch_payload(
        {
            "id": 1001,
            "batch_number": 42,
            "name": "Image Test Recipe",
            "session_name": "Image Test Batch",
            "recipe": {"image": {"url": image_url}},
        }
    )
    assert session is not None
    return session


async def test_image_platform_exposes_icon_and_recipe_images(hass) -> None:
    """The platform adds a static icon and only recipe images with URLs."""
    image_session = _session(image_url="https://example.invalid/recipe.png")
    no_image_session = _session(image_url=None)
    snapshot = GrainfatherSnapshot(
        account=GrainfatherAccount(None, None, None, None),
        brew_sessions=(image_session, no_image_session),
        fermentation_devices=(),
    )
    coordinator = _Coordinator(snapshot)
    entry = SimpleNamespace(entry_id="test-entry")
    hass.data[DOMAIN] = {entry.entry_id: coordinator}
    entities: list[Any] = []

    await async_setup_entry(hass, entry, entities.extend)

    assert len(entities) == 2
    icon, recipe_image = entities
    assert isinstance(icon, GrainfatherIntegrationIconImage)
    assert await icon.async_image()
    assert isinstance(recipe_image, GrainfatherSessionRecipeImage)
    assert recipe_image.available is True
    assert recipe_image.image_url == "https://example.invalid/recipe.png"
    assert recipe_image.device_info is not None
    coordinator.data = GrainfatherSnapshot(
        account=snapshot.account,
        brew_sessions=(),
        fermentation_devices=(),
    )
    assert recipe_image.available is False
    assert recipe_image.image_url is None
    assert recipe_image.device_info is None
