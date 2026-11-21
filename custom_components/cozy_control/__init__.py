"""Cozy Control: keep the house comfortable by following the weather."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.start import async_at_started

from . import engine
from .const import (
    CONF_BED_ENABLED,
    CONF_BED_END,
    CONF_BED_START,
    DEFAULT_BED_END,
    DEFAULT_BED_START,
    PLATFORMS,
    indoor_profiles,
)
from .coordinator import ComfortCoordinator

type CozyControlConfigEntry = ConfigEntry[ComfortCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: CozyControlConfigEntry) -> bool:
    """Set up one thermostat controller."""
    coordinator = ComfortCoordinator(hass, entry)
    await coordinator.async_load_state()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    _schedule_bedtime_refreshes(hass, entry, coordinator)
    coordinator.start_listening()
    _schedule_indoor_refreshes(hass, entry, coordinator)

    async def _started(_hass: HomeAssistant) -> None:
        # Everything else has loaded now: check again with the full picture.
        await coordinator.async_request_refresh()

    if not hass.is_running:  # booting: look again once everything else has loaded
        entry.async_on_unload(async_at_started(hass, _started))
    return True


def _schedule_bedtime_refreshes(
    hass: HomeAssistant, entry: CozyControlConfigEntry, coordinator: ComfortCoordinator
) -> None:
    """Re-evaluate right when bedtime starts and ends, not up to an interval later."""
    if not entry.options.get(CONF_BED_ENABLED, False):
        return

    async def _refresh(_now) -> None:
        await coordinator.async_request_refresh()

    for key, default in ((CONF_BED_START, DEFAULT_BED_START), (CONF_BED_END, DEFAULT_BED_END)):
        try:
            at = engine.parse_clock(entry.options.get(key, default))
        except ValueError:
            continue
        entry.async_on_unload(
            async_track_time_change(hass, _refresh, hour=at.hour, minute=at.minute, second=0)
        )


def _schedule_indoor_refreshes(
    hass: HomeAssistant, entry: CozyControlConfigEntry, coordinator: ComfortCoordinator
) -> None:
    """Switch indoor sensors exactly when a time window starts or ends."""

    async def _refresh(_now) -> None:
        await coordinator.async_request_refresh()

    moments = {
        t
        for profile in indoor_profiles(entry.options)
        for t in (profile.start, profile.end)
        if t is not None
    }
    for at in moments:
        entry.async_on_unload(
            async_track_time_change(hass, _refresh, hour=at.hour, minute=at.minute, second=0)
        )


async def async_unload_entry(hass: HomeAssistant, entry: CozyControlConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: CozyControlConfigEntry) -> None:
    """Reload when the options change so the new settings apply."""
    await hass.config_entries.async_reload(entry.entry_id)
