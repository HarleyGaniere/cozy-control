"""Sensors: what the integration decided and why."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CozyControlConfigEntry
from .const import PRESENCE_OPTIONS, STATUS_OPTIONS, indoor_profiles
from .entity import ComfortEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CozyControlConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            OutdoorTemperatureSensor(coordinator, "outdoor_temperature"),
            TargetTemperatureSensor(coordinator, "target_temperature"),
            StatusSensor(coordinator, "status"),
            *([PresenceSensor(coordinator, "presence")] if coordinator.sources else []),
            *([IndoorTemperatureSensor(coordinator, "indoor_temperature")] if indoor_profiles(coordinator.config_entry.options) else []),
            *([OpeningsSensor(coordinator, "openings")] if coordinator.contacts else []),
        ]
    )


class _TemperatureSensor(ComfortEntity, SensorEntity):
    # Values are Celsius; Home Assistant shows them in the user's unit system.
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1


class OutdoorTemperatureSensor(_TemperatureSensor):
    """The outdoor temperature the rules are using."""

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        return None if data is None or data.outdoor is None else round(data.outdoor, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"sources_and_weights": self.coordinator.outdoor_used}


class TargetTemperatureSensor(_TemperatureSensor):
    """The indoor target. For heat/cool range mode this is the middle."""

    @property
    def native_value(self) -> float | None:
        decision = self.coordinator.data.decision if self.coordinator.data else None
        if decision is None:
            return None
        if decision.setpoint is not None:
            return round(decision.setpoint, 2)
        if decision.low is not None and decision.high is not None:
            return round((decision.low + decision.high) / 2, 2)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        decision = self.coordinator.data.decision if self.coordinator.data else None
        if decision is None:
            return {}
        return {
            "mode": decision.mode,
            "target_low_c": decision.low,
            "target_high_c": decision.high,
        }


class StatusSensor(ComfortEntity, SensorEntity):
    """Why the thermostat is set the way it is."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUS_OPTIONS

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        return None if data is None else data.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {}
        decision = data.decision
        return {
            "last_evaluated": data.updated.isoformat(),
            "changed_thermostat": data.applied,
            "mode": None if decision is None else decision.mode,
            "heating_allowed": None if decision is None else decision.heat_allowed,
            "cooling_allowed": None if decision is None else decision.cool_allowed,
        }


class PresenceSensor(ComfortEntity, SensorEntity):
    """Whether anyone is home, and what each phone says.

    "Away" appears only after everyone has been away for the delay set in the
    settings; until then the thermostat keeps following the normal table.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = PRESENCE_OPTIONS

    @property
    def native_value(self) -> str:
        presence = self.coordinator.presence
        # "away" is only reported once the delay is over.
        if presence.state == "away" and not presence.away:
            return "home"
        return presence.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        presence = self.coordinator.presence
        return {
            "away_mode_active": presence.away,
            "everyone_away_since": (
                presence.away_since.isoformat() if presence.away_since else None
            ),
            "sources": presence.sources,
        }


class OpeningsSensor(ComfortEntity, SensorEntity):
    """How many watched windows and doors are open right now."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int:
        return len(self.coordinator.openings.open)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        openings = self.coordinator.openings
        hass = self.coordinator.hass
        names = []
        for entity_id in openings.open:
            state = hass.states.get(entity_id)
            names.append((state.attributes.get("friendly_name") if state else None) or entity_id)
        return {
            "open": names,
            "open_since": openings.open_since.isoformat() if openings.open_since else None,
            "thermostat_held_off": openings.holding_off,
        }


class IndoorTemperatureSensor(_TemperatureSensor):
    """The weighted indoor temperature of the sensors in use right now."""

    @property
    def native_value(self) -> float | None:
        average = self.coordinator.indoor_reading.average
        return None if average is None else round(average, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        reading = self.coordinator.indoor_reading
        return {
            "sources_and_weights": reading.weights,
            "time_window": reading.window,
            "thermostat_reading_c": reading.thermostat,
            "target_shift_c": round(reading.offset, 2),
        }
