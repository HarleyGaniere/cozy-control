"""Buttons: update now, "I'm cold", "I'm warm" and undo."""

from __future__ import annotations

from typing import Any

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
    coordinator = entry.runtime_data
    async_add_entities(
        [
            UpdateNowButton(coordinator, "update_now"),
            FeelButton(coordinator, "feel_cold", warmer=True),
            FeelButton(coordinator, "feel_warm", warmer=False),
            UndoFeelButton(coordinator, "undo_feel"),
        ]
    )


class UpdateNowButton(ComfortEntity, ButtonEntity):
    """Read the weather and update the thermostat now."""

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()


class FeelButton(ComfortEntity, ButtonEntity):
    """I'm cold (or warm): make it warmer (or cooler) now and remember it in the table."""

    def __init__(self, coordinator, key: str, *, warmer: bool) -> None:
        super().__init__(coordinator, key)
        self._warmer = warmer

    async def async_press(self) -> None:
        await self.coordinator.async_feedback(self._warmer)


class UndoFeelButton(ComfortEntity, ButtonEntity):
    """Undo the last "I'm cold" or "I'm warm"."""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        undo = self.coordinator.feedback_undo
        return {"last_change": undo.get("message") if undo else None}

    async def async_press(self) -> None:
        await self.coordinator.async_undo_feedback()
