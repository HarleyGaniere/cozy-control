"""Button to re-evaluate right now."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CozyControlConfigEntry
from .entity import ComfortEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CozyControlConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([UpdateNowButton(entry.runtime_data, "update_now")])


class UpdateNowButton(ComfortEntity, ButtonEntity):
    """Read the weather and update the thermostat now."""

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()
