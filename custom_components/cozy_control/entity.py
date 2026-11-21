"""Shared entity base for Cozy Control."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ComfortCoordinator


class ComfortEntity(CoordinatorEntity[ComfortCoordinator]):
    """Base class: one device per configured thermostat."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ComfortCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Cozy Control",
            entry_type=DeviceEntryType.SERVICE,
        )
