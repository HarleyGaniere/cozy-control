"""Switch to pause and resume the automation."""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import CozyControlConfigEntry, engine
from .entity import ComfortEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CozyControlConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            EnabledSwitch(coordinator, "enabled"),
            WindowsOpenSwitch(coordinator, "windows_open"),
            *[TrackSourceSwitch(coordinator, entity_id) for entity_id in coordinator.sources],
        ]
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "morning_briefing",
        {vol.Optional("notify_entity"): cv.entity_id},
        "async_service_briefing",
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        "answer",
        {vol.Required("answer"): vol.All(cv.string, vol.Lower, vol.In(["yes", "no"]))},
        "async_service_answer",
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        "windows_opened",
        {
            vol.Optional("hours"): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=72)),
            vol.Optional("until"): cv.time,
        },
        "async_service_windows_opened",
    )
    platform.async_register_entity_service("windows_closed", None, "async_service_windows_closed")


class EnabledSwitch(ComfortEntity, SwitchEntity):
    """On: the thermostat follows the rules. Off: it is left alone."""

    @property
    def is_on(self) -> bool:
        return self.coordinator.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_enabled(False)


class TrackSourceSwitch(ComfortEntity, SwitchEntity):
    """On: this phone or person counts for Away mode. Off: it is ignored."""

    def __init__(self, coordinator, source: str) -> None:
        super().__init__(coordinator, f"track_{source}")
        self._source = source
        self._attr_translation_key = "track_source"
        state = coordinator.hass.states.get(source)
        name = state.attributes.get("friendly_name") if state else None
        self._attr_translation_placeholders = {"source": name or source}

    @property
    def is_on(self) -> bool:
        return self._source not in self.coordinator.disabled_sources

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"source": self._source}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_source_enabled(self._source, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_source_enabled(self._source, False)


class WindowsOpenSwitch(ComfortEntity, SwitchEntity):
    """On: the windows are open and the thermostat is off. Off: it follows the rules.

    Share this switch with a voice assistant so "I have opened the windows" and
    "I have shut the windows" can turn it on and off.
    """

    @property
    def is_on(self) -> bool:
        return self.coordinator.windows_open

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        until = self.coordinator.windows_resume_at
        return {"resumes_at": until.isoformat() if until else None}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_windows_opened()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_windows_closed()

    # -- services ---------------------------------------------------------------

    async def async_service_briefing(self, notify_entity: str | None = None) -> dict[str, Any]:
        return await self.coordinator.async_briefing(notify_entity)

    async def async_service_answer(self, answer: str) -> dict[str, Any]:
        return await self.coordinator.async_answer(answer == "yes")

    async def async_service_windows_opened(
        self, hours: float | None = None, until: time | None = None
    ) -> None:
        resume_at = None
        now = dt_util.now()
        if until is not None:
            resume_at = engine.next_resume(now, until)
        elif hours is not None:
            resume_at = now + timedelta(hours=hours)
        await self.coordinator.async_windows_opened(resume_at)

    async def async_service_windows_closed(self) -> None:
        await self.coordinator.async_windows_closed()
