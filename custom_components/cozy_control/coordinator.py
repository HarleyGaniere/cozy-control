"""Coordinator: reads the weather, decides, and drives the thermostat."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import engine
from .const import (
    CONF_AWAY_SETPOINTS,
    CONF_BED_SETPOINTS,
    CONF_CLIMATE,
    CONF_CONTACT_DELAY,
    CONF_FEEDBACK_BURST,
    CONF_FEEDBACK_LIMIT,
    CONF_INDOOR_MAX_OFFSET,
    CONF_INTERPOLATE,
    CONF_INTERVAL,
    CONF_MIN_CHANGE,
    CONF_OUTDOOR_WEIGHTS,
    CONF_PRESENCE_DELAY,
    CONF_PRESENCE_MAX_ACCURACY,
    CONF_PRESENCE_RADIUS,
    CONF_RANGE_WIDTH,
    CONF_SAFETY_SENSORS,
    CONF_SETPOINTS,
    CONF_TIME_FORMAT,
    CONF_USE_FORECAST,
    CONF_WIN_MAX_HOURS,
    CONF_WIN_RESUME,
    DEFAULT_AWAY_SETPOINTS,
    DEFAULT_BED_SETPOINTS,
    DEFAULT_CONTACT_DELAY,
    DEFAULT_FEEDBACK_BURST,
    DEFAULT_FEEDBACK_LIMIT,
    DEFAULT_FEEDBACK_STEP,
    DEFAULT_INDOOR_MAX_OFFSET,
    DEFAULT_INTERVAL,
    DEFAULT_MIN_CHANGE,
    DEFAULT_PRESENCE_DELAY,
    DEFAULT_PRESENCE_MAX_ACCURACY,
    DEFAULT_PRESENCE_RADIUS,
    DEFAULT_RANGE_WIDTH,
    DEFAULT_SETPOINTS,
    DEFAULT_WIN_MAX_HOURS,
    DEFAULT_WIN_RESUME,
    DOMAIN,
    PENDING_MINUTES,
    STATUS_APPLY_FAILED,
    STATUS_PAUSED,
    STATUS_SOURCE_UNAVAILABLE,
    STATUS_THERMOSTAT_UNAVAILABLE,
    TIME_12H,
    briefing_dates,
    contact_sources,
    display_unit,
    indoor_profiles,
    outdoor_sources,
    presence_sources,
    safety_settings_from_options,
    settings_from_options,
    window_settings_from_options,
)

_LOGGER = logging.getLogger(__name__)

RETRY_SECONDS = 60  # how soon to look again while the weather or thermostat is unavailable

# The tables "I'm cold" and "I'm warm" can tune, with their defaults and names
FEEDBACK_TABLES = {
    CONF_SETPOINTS: (DEFAULT_SETPOINTS, "temperature table"),
    CONF_BED_SETPOINTS: (DEFAULT_BED_SETPOINTS, "bedtime table"),
    CONF_AWAY_SETPOINTS: (DEFAULT_AWAY_SETPOINTS, "away table"),
}


@dataclass
class ComfortData:
    """One evaluation of the comfort logic."""

    status: str
    outdoor: float | None  # Celsius
    decision: engine.Decision | None
    applied: bool
    updated: datetime


@dataclass
class Presence:
    """Who is home, as last worked out."""

    state: str  # home / away / unknown
    away: bool  # Away mode is in effect (everyone away for the whole delay)
    away_since: datetime | None
    sources: dict[str, dict[str, Any]]


@dataclass
class Openings:
    """Which windows and doors are open, as last read."""

    open: list[str]  # entity ids reporting open (whether or not the delay is over)
    holding_off: bool  # the thermostat is held off because of them
    open_since: datetime | None


@dataclass
class IndoorReading:
    """The indoor temperature the rules are steering towards."""

    average: float | None  # weighted average of the active sensors (Celsius)
    thermostat: float | None  # the thermostat's own reading
    offset: float  # how much the thermostat's targets are shifted
    weights: dict[str, float]  # sensors actually used and their weights
    window: str | None  # the time window of the active profile, if it has one


@dataclass
class Pending:
    """A question that was asked and is waiting for a yes or no."""

    yes_action: str
    no_action: str
    expires: datetime


class ComfortCoordinator(DataUpdateCoordinator[ComfortData]):
    """Evaluates the comfort rules on a schedule."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        minutes = int(entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.title}",
            config_entry=entry,
            update_interval=timedelta(minutes=max(1, minutes)),
        )
        self.enabled = True
        self.windows_open = False
        self.windows_resume_at: datetime | None = None
        self.pending: Pending | None = None
        self.disabled_sources: set[str] = set()
        self.presence = Presence(engine.PRESENCE_UNKNOWN, False, None, {})
        self.openings = Openings([], False, None)
        self.safety: str | None = None
        self.outdoor_used: dict[str, float] = {}
        self.indoor_reading = IndoorReading(None, None, 0.0, {}, None)
        self.indoor: tuple[float | None, float | None] = (None, None)  # hottest, coldest
        self._open_since: datetime | None = None
        self._cancel_open: CALLBACK_TYPE | None = None
        self._away_since: datetime | None = None
        self._cancel_away: CALLBACK_TYPE | None = None
        self._cancel_resume: CALLBACK_TYPE | None = None
        self._cancel_retry: CALLBACK_TYPE | None = None
        self.feedback_undo: dict[str, Any] | None = None  # the table before the last comfort change
        # Where each changed row stood at the start of today, for the daily limit.
        self.feedback_day: dict[str, Any] = {}
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")

    # -- pause switch and window state survive restarts -------------------------

    async def async_load_state(self) -> None:
        stored = await self._store.async_load()
        if stored is None:
            return
        self.enabled = bool(stored.get("enabled", True))
        self.windows_open = bool(stored.get("windows_open", False))
        self.disabled_sources = {str(e) for e in stored.get("disabled_sources", [])}
        raw = stored.get("windows_resume_at")
        self.windows_resume_at = dt_util.parse_datetime(raw) if raw else None
        undo = stored.get("feedback_undo")
        self.feedback_undo = undo if isinstance(undo, dict) and undo.get("key") in FEEDBACK_TABLES else None
        day = stored.get("feedback_day")
        self.feedback_day = day if isinstance(day, dict) else {}
        self._schedule_resume()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "enabled": self.enabled,
                "windows_open": self.windows_open,
                "disabled_sources": sorted(self.disabled_sources),
                "windows_resume_at": (
                    self.windows_resume_at.isoformat() if self.windows_resume_at else None
                ),
                "feedback_undo": self.feedback_undo,
                "feedback_day": self.feedback_day,
            }
        )

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        await self._async_save()
        await self.async_refresh()

    # -- "I'm cold" / "I'm warm" -------------------------------------------------

    def _table_in_use(self) -> str | None:
        """The options key of the table setting the target now, or None.

        None while nothing comes from a table: the thermostat is off (mild
        weather, windows open, heating and cooling switched off) or a safety
        limit is in charge.
        """
        decision = self.data.decision if self.data else None
        if (
            decision is None
            or decision.mode == engine.OFF
            or decision.reason in (engine.R_SAFETY_HOT, engine.R_SAFETY_COLD)
        ):
            return None
        if decision.away:
            return CONF_AWAY_SETPOINTS
        if decision.bedtime:
            return CONF_BED_SETPOINTS
        return CONF_SETPOINTS

    def _say(self, celsius: float) -> str:
        unit = display_unit(self.hass, self.config_entry.options)
        return f"{engine._fmt(engine.from_celsius(celsius, unit), 1)} {unit}"

    async def async_feedback(self, warmer: bool, step: float | None = None) -> dict[str, Any]:
        """Someone is cold (or warm): tune the table in use at today's outdoor temperature.

        ``step`` is in the menus' unit; without it the change is 0.5 °C (1 °F).
        Saving the table re-evaluates straight away, so the thermostat follows
        within seconds. The table before the change is kept for one undo, which
        covers every press in a burst. A row moves at most the daily limit.
        """
        options = self.config_entry.options
        unit = display_unit(self.hass, options)
        if step is None:
            step_c = 1.0 * 5.0 / 9.0 if unit == engine.UNIT_F else DEFAULT_FEEDBACK_STEP
        else:
            step_c = engine.delta_to_celsius(float(step), unit)
        key = self._table_in_use()
        outdoor = self.data.outdoor if self.data else None
        if key is None or outdoor is None:
            return {
                "changed": False,
                "message": "The thermostat isn't following a temperature table right now, "
                "so I didn't change anything.",
            }
        default, table_name = FEEDBACK_TABLES[key]
        points = [(float(o), float(i)) for o, i in options.get(key, default)]
        interpolate = bool(options.get(CONF_INTERPOLATE, True))
        now = dt_util.now()

        # Daily limit: a row can't move more than this from where it stood this
        # morning, however often the button is pressed.
        at = engine.round_to_step(outdoor, engine.FEEDBACK_SNAP)
        row = f"{key}|{at:g}"
        today = now.date().isoformat()
        if self.feedback_day.get("date") != today:
            self.feedback_day = {"date": today, "start": {}}
        starts: dict[str, float] = self.feedback_day.setdefault("start", {})
        start = starts.get(row)
        if start is None:
            start = round(engine.setpoint_for(at, sorted(points), interpolate), 1)
            for x, y in points:
                if abs(x - at) < 1e-6:
                    start = round(y, 1)
        limit = float(options.get(CONF_FEEDBACK_LIMIT, DEFAULT_FEEDBACK_LIMIT))
        low, high = (start - limit, start + limit) if limit > 0 else (engine.FEEDBACK_MIN, engine.FEEDBACK_MAX)

        new_points, at, old, new = engine.nudge_setpoints(
            points,
            outdoor,
            step_c if warmer else -step_c,
            interpolate,
            low=low,
            high=high,
        )
        if new == old:
            daily = limit > 0 and (
                (warmer and high < engine.FEEDBACK_MAX) or (not warmer and low > engine.FEEDBACK_MIN)
            )
            if daily:
                message = (
                    f"The {table_name} has already moved as far as it can today "
                    f"for {self._say(at)} outside, so I left it at {self._say(new)}."
                )
            else:
                message = (
                    f"The {table_name} is already at its limit of {self._say(new)} "
                    f"for {self._say(at)} outside."
                )
            _LOGGER.info("%s", message)
            return {"changed": False, "message": message}
        starts.setdefault(row, start)
        word = "Warmer" if warmer else "Cooler"
        message = (
            f"{word}: the {table_name} now aims for {self._say(new)} "
            f"at {self._say(at)} outside, instead of {self._say(old)}."
        )

        # Presses close together are one change: undo puts the table back as it
        # was before the first of them.
        burst = timedelta(minutes=float(options.get(CONF_FEEDBACK_BURST, DEFAULT_FEEDBACK_BURST)))
        undo = self.feedback_undo
        last = dt_util.parse_datetime(str(undo.get("last", ""))) if undo else None
        if undo and undo.get("key") == key and last is not None and now - last <= burst:
            before = undo["points"]
        else:
            before = [list(p) for p in points]
        self.feedback_undo = {
            "key": key,
            "points": before,
            "message": message,
            "last": now.isoformat(),
        }
        await self._async_save()
        _LOGGER.info("%s", message)
        # Saving the options reloads the entry, which applies the new target.
        self.hass.config_entries.async_update_entry(
            self.config_entry, options={**options, key: [list(p) for p in new_points]}
        )
        return {
            "changed": True,
            "table": key,
            "outdoor": at,
            "old": old,
            "new": new,
            "message": message,
        }

    async def async_undo_feedback(self) -> dict[str, Any]:
        """Put the table back as it was before the last "I'm cold" or "I'm warm".

        Presses close together count as one, so this undoes the whole burst.
        """
        undo = self.feedback_undo
        if not undo:
            return {"changed": False, "message": "There is no comfort change to undo."}
        _default, table_name = FEEDBACK_TABLES[undo["key"]]
        self.feedback_undo = None
        await self._async_save()
        message = f"Undone: the {table_name} is back as it was."
        _LOGGER.info("%s", message)
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={**self.config_entry.options, undo["key"]: undo["points"]},
        )
        return {"changed": True, "table": undo["key"], "message": message}

    async def async_shutdown(self) -> None:
        self._stop_resume_timer()
        self._stop_away_timer()
        self._stop_open_timer()
        self._stop_retry_timer()
        await super().async_shutdown()

    # -- presence ---------------------------------------------------------------

    @property
    def sources(self) -> list[str]:
        """Every phone/person chosen in the settings (empty when Away mode is off)."""
        return presence_sources(self.config_entry.options)

    @property
    def contacts(self) -> list[str]:
        """Window and door sensors chosen in the settings (empty when switched off)."""
        return contact_sources(self.config_entry.options)

    def start_listening(self) -> None:
        """React the moment a watched phone, person, window or door changes."""
        sources = [*self.sources, *self.contacts]
        profiles = indoor_profiles(self.config_entry.options)
        if profiles:
            sources += [
                self.config_entry.data[CONF_CLIMATE],
                *{n for p in profiles for n, _ in p.sources},
            ]
        if safety_settings_from_options(self.config_entry.options) is not None:
            # Indoor temperatures are watched so a limit is acted on in seconds,
            # not at the next scheduled check.
            sources += [
                self.config_entry.data[CONF_CLIMATE],
                *self.config_entry.options.get(CONF_SAFETY_SENSORS, []),
            ]
        if not sources:
            return

        async def _changed(_event) -> None:
            await self.async_request_refresh()

        self.config_entry.async_on_unload(
            async_track_state_change_event(self.hass, sources, _changed)
        )

    async def async_set_source_enabled(self, entity_id: str, enabled: bool) -> None:
        if enabled:
            self.disabled_sources.discard(entity_id)
        else:
            self.disabled_sources.add(entity_id)
        await self._async_save()
        await self.async_refresh()

    def _read_temperature(self, entity_id: str) -> float | None:
        """A temperature in Celsius from a thermostat or a sensor, or None."""
        system_unit = self.hass.config.units.temperature_unit
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        if state.domain == "climate":
            raw, unit = state.attributes.get("current_temperature"), system_unit
        else:
            raw = state.state
            unit = state.attributes.get("unit_of_measurement") or system_unit
        try:
            return None if raw is None else engine.to_celsius(float(raw), unit)
        except (TypeError, ValueError):
            return None

    def _update_indoor(self, thermostat: State | None, now: datetime) -> float:
        """Work out the weighted indoor temperature and how far to shift the targets.

        Returns the shift in Celsius (0 when the feature is off, there is no
        usable reading, or the thermostat is the only source).
        """
        self.indoor_reading = IndoorReading(None, None, 0.0, {}, None)
        profiles = indoor_profiles(self.config_entry.options)
        if not profiles or thermostat is None:
            return 0.0
        own = self._read_temperature(thermostat.entity_id)
        profile = engine.active_indoor_profile(profiles, now.time())
        if profile is None:
            self.indoor_reading = IndoorReading(None, own, 0.0, {}, None)
            return 0.0
        readings = {name: self._read_temperature(name) for name, _ in profile.sources}
        average, used = engine.weighted_average(readings, profile)
        window = (
            None
            if profile.start is None or profile.end is None
            else f"{engine.format_clock(profile.start)}-{engine.format_clock(profile.end)}"
        )
        offset = 0.0
        if average is not None and own is not None:
            limit = abs(
                float(
                    self.config_entry.options.get(
                        CONF_INDOOR_MAX_OFFSET, DEFAULT_INDOOR_MAX_OFFSET
                    )
                )
            )
            offset = max(-limit, min(limit, own - average))
        self.indoor_reading = IndoorReading(average, own, offset, used, window)
        return offset

    def _update_safety(self, thermostat: State | None) -> str | None:
        """Check the indoor temperatures against the safety limits."""
        limits = safety_settings_from_options(self.config_entry.options)
        if limits is None or thermostat is None:
            self.safety = None
            self.indoor = (None, None)
            return None
        system_unit = self.hass.config.units.temperature_unit
        readings: list[float] = []
        raw = thermostat.attributes.get("current_temperature")
        try:
            if raw is not None:
                readings.append(engine.to_celsius(float(raw), system_unit))
        except (TypeError, ValueError):
            pass
        for entity_id in self.config_entry.options.get(CONF_SAFETY_SENSORS, []):
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                continue
            unit = state.attributes.get("unit_of_measurement") or system_unit
            try:
                readings.append(engine.to_celsius(float(state.state), unit))
            except (TypeError, ValueError):
                continue
        hottest = max(readings) if readings else None
        coldest = min(readings) if readings else None
        self.indoor = (hottest, coldest)
        self.safety = engine.safety_state(hottest, coldest, limits, self.safety)
        return self.safety

    def _stop_open_timer(self) -> None:
        if self._cancel_open is not None:
            self._cancel_open()
            self._cancel_open = None

    def _update_openings(self, now: datetime) -> bool:
        """Read the window and door sensors. Returns True when they hold the thermostat off.

        Unavailable sensors are ignored. Opening only counts after the delay,
        so a door held open for a moment does not switch the heating off;
        closing the last one takes effect immediately.
        """
        contacts = self.contacts
        if not contacts:
            self._open_since = None
            self._stop_open_timer()
            self.openings = Openings([], False, None)
            return False

        open_now = []
        for entity_id in contacts:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state == "on":
                open_now.append(entity_id)

        if not open_now:
            self._open_since = None
            self._stop_open_timer()
            self.openings = Openings([], False, None)
            return False

        if self._open_since is None:
            self._open_since = now
        delay = float(
            self.config_entry.options.get(CONF_CONTACT_DELAY, DEFAULT_CONTACT_DELAY)
        )
        holding = engine.held_for(self._open_since, now, delay)
        if holding:
            self._stop_open_timer()
        elif self._cancel_open is None:

            async def _wake(_now: datetime) -> None:
                self._cancel_open = None
                await self.async_refresh()

            self._cancel_open = async_track_point_in_time(
                self.hass, _wake, self._open_since + timedelta(minutes=delay)
            )
        self.openings = Openings(open_now, holding, self._open_since)
        return holding

    def _stop_away_timer(self) -> None:
        if self._cancel_away is not None:
            self._cancel_away()
            self._cancel_away = None

    def _read_sources(self) -> dict[str, engine.SourceReading]:
        options = self.config_entry.options
        radius = float(options.get(CONF_PRESENCE_RADIUS, DEFAULT_PRESENCE_RADIUS))
        max_acc = float(options.get(CONF_PRESENCE_MAX_ACCURACY, DEFAULT_PRESENCE_MAX_ACCURACY))
        home_lat, home_lon = self.hass.config.latitude, self.hass.config.longitude

        def number(attrs, name) -> float | None:
            try:
                return None if attrs.get(name) is None else float(attrs[name])
            except (TypeError, ValueError):
                return None

        readings: dict[str, engine.SourceReading] = {}
        for entity_id in self.sources:
            if entity_id in self.disabled_sources:
                continue
            state = self.hass.states.get(entity_id)
            attrs = state.attributes if state else {}
            readings[entity_id] = engine.read_source(
                state.state if state else None,
                number(attrs, "latitude"),
                number(attrs, "longitude"),
                number(attrs, "gps_accuracy"),
                home_lat,
                home_lon,
                radius,
                max_acc,
            )
        return readings

    def _update_presence(self, now: datetime) -> bool:
        """Work out who is home. Returns True when Away mode is in effect."""
        sources = self.sources
        if not sources:
            self._away_since = None
            self._stop_away_timer()
            self.presence = Presence(engine.PRESENCE_UNKNOWN, False, None, {})
            return False

        readings = self._read_sources()
        state = engine.combine_presence(list(readings.values()))
        if state == engine.PRESENCE_AWAY:
            if self._away_since is None:
                self._away_since = now
        else:
            self._away_since = None
            self._stop_away_timer()

        delay = float(
            self.config_entry.options.get(CONF_PRESENCE_DELAY, DEFAULT_PRESENCE_DELAY)
        )
        away = engine.away_confirmed(self._away_since, now, delay)
        if state == engine.PRESENCE_AWAY and not away and self._cancel_away is None:
            # Wake up exactly when the delay ends, not up to an interval later.
            async def _wake(_now: datetime) -> None:
                self._cancel_away = None
                await self.async_refresh()

            self._cancel_away = async_track_point_in_time(
                self.hass, _wake, self._away_since + timedelta(minutes=delay)
            )
        elif away:
            self._stop_away_timer()

        self.presence = Presence(
            state,
            away,
            self._away_since,
            {
                entity_id: {
                    "enabled": entity_id not in self.disabled_sources,
                    "home": readings[entity_id].home if entity_id in readings else None,
                    "distance_m": (
                        readings[entity_id].distance_m if entity_id in readings else None
                    ),
                }
                for entity_id in sources
            },
        )
        return away

    # -- windows ----------------------------------------------------------------

    def _stop_resume_timer(self) -> None:
        if self._cancel_resume is not None:
            self._cancel_resume()
            self._cancel_resume = None

    def _schedule_resume(self) -> None:
        """Wake up exactly when the windows-open period ends."""
        self._stop_resume_timer()
        if not self.windows_open or self.windows_resume_at is None:
            return

        async def _wake(_now: datetime) -> None:
            self._cancel_resume = None
            await self.async_refresh()

        self._cancel_resume = async_track_point_in_time(
            self.hass, _wake, self.windows_resume_at
        )

    def _resume_for(self, now: datetime, at_resume_time: bool) -> datetime | None:
        """When to resume: the configured resume time (if asked) capped by the safety limit."""
        options = self.config_entry.options
        at = None
        if at_resume_time:
            at = engine.parse_clock(options.get(CONF_WIN_RESUME, DEFAULT_WIN_RESUME))
        hours = float(options.get(CONF_WIN_MAX_HOURS, DEFAULT_WIN_MAX_HOURS))
        return engine.next_resume(now, at, hours)

    async def async_windows_opened(
        self, resume_at: datetime | None = None, *, at_resume_time: bool = False
    ) -> None:
        """The windows are open: switch the thermostat off until told otherwise."""
        now = dt_util.now()
        self.windows_open = True
        self.windows_resume_at = resume_at or self._resume_for(now, at_resume_time)
        self.pending = None
        self._schedule_resume()
        await self._async_save()
        await self.async_refresh()

    async def async_windows_closed(self) -> None:
        """The windows are shut: the thermostat follows the rules again."""
        self.windows_open = False
        self.windows_resume_at = None
        self.pending = None
        self._stop_resume_timer()
        await self._async_save()
        await self.async_refresh()

    def _resume_text(self) -> str:
        options = self.config_entry.options
        hour12 = options.get(CONF_TIME_FORMAT) == TIME_12H
        try:
            at = engine.parse_clock(options.get(CONF_WIN_RESUME, DEFAULT_WIN_RESUME))
        except ValueError:
            return "this evening"
        return engine.format_clock(at, hour12)

    # -- forecast, briefing and answers -----------------------------------------

    async def _forecast_today(self) -> tuple[float | None, float | None]:
        """Today's forecast high and low in Celsius, or (None, None)."""
        if not self.config_entry.options.get(CONF_USE_FORECAST, True):
            return None, None
        entity_id = next(
            (e for e in outdoor_sources(self.config_entry) if e.startswith("weather.")), None
        )
        if entity_id is None:
            return None, None
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": entity_id, "type": "daily"},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            _LOGGER.debug("No daily forecast from %s: %s", entity_id, err)
            return None, None
        items = (response or {}).get(entity_id, {}).get("forecast") or []
        if not items:
            return None, None
        today = dt_util.now().date()
        item = items[0]
        for candidate in items:
            when = dt_util.parse_datetime(str(candidate.get("datetime", "")))
            if when is not None and dt_util.as_local(when).date() == today:
                item = candidate
                break
        state = self.hass.states.get(entity_id)
        unit = (state.attributes.get("temperature_unit") if state else None) or (
            self.hass.config.units.temperature_unit
        )

        def c(value: Any) -> float | None:
            try:
                return None if value is None else engine.to_celsius(float(value), unit)
            except (TypeError, ValueError):
                return None

        return c(item.get("temperature")), c(item.get("templow"))

    async def async_briefing(self, notify_entity: str | None = None) -> dict[str, Any]:
        """The morning briefing: advice for today, and a question when one helps.

        Running it also ends any "windows are open" period, so the thermostat
        starts the day following the rules again.
        """
        options = self.config_entry.options
        if self.windows_open:
            await self.async_windows_closed()
        else:
            self.pending = None

        now = dt_util.now()
        seasons = briefing_dates(options)
        if seasons is not None and not engine.in_date_ranges(now.date(), seasons):
            return {"active": False, "advice": None, "message": "", "question": None}

        outdoor = self._read_outdoor()
        if outdoor is None:
            message = "I could not read the outdoor temperature, so I have no advice today."
            await self._speak(notify_entity, message)
            return {"active": True, "advice": None, "message": message, "question": None}

        high, low = await self._forecast_today()
        data = self.data
        if data is not None and data.decision is not None:
            running = data.decision.mode != engine.OFF
        else:
            thermostat = self._thermostat()
            running = thermostat is not None and thermostat.state != "off"
        advice = engine.advise(
            high,
            low,
            outdoor,
            window_settings_from_options(options),
            running,
            unit=display_unit(self.hass, options),
            resume_text=self._resume_text(),
        )
        if advice.question:
            self.pending = Pending(
                advice.yes_action,
                advice.no_action,
                now + timedelta(minutes=PENDING_MINUTES),
            )
        spoken = f"{advice.message} {advice.question}" if advice.question else advice.message
        await self._speak(notify_entity, spoken)
        return {
            "active": True,
            "advice": advice.kind,
            "message": advice.message,
            "question": advice.question,
        }

    async def _speak(self, notify_entity: str | None, text: str) -> None:
        if not notify_entity:
            return
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {"entity_id": notify_entity, "message": text},
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Could not send the briefing to %s: %s", notify_entity, err)

    async def async_answer(self, yes: bool) -> dict[str, Any]:
        """Answer the question from the last briefing."""
        pending = self.pending
        if pending is None or pending.expires <= dt_util.now():
            self.pending = None
            return {"handled": False, "message": "There is no question waiting for an answer."}
        self.pending = None
        action = pending.yes_action if yes else pending.no_action
        if action == engine.ACT_OPEN:
            await self.async_windows_opened(at_resume_time=True)
            until = self.windows_resume_at
            when = (
                engine.format_clock(
                    dt_util.as_local(until).time(),
                    self.config_entry.options.get(CONF_TIME_FORMAT) == TIME_12H,
                )
                if until
                else "you tell me the windows are closed"
            )
            return {"handled": True, "message": f"Okay, the thermostat is off until {when}."}
        return {"handled": True, "message": "Okay, I will keep the thermostat running."}

    # -- reading --------------------------------------------------------------

    def _read_one_outdoor(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        system_unit = self.hass.config.units.temperature_unit
        if state.domain == "weather":
            raw = state.attributes.get("temperature")
            unit = state.attributes.get("temperature_unit") or system_unit
        else:
            raw = state.state
            unit = state.attributes.get("unit_of_measurement") or system_unit
        try:
            return engine.to_celsius(float(raw), unit)
        except (TypeError, ValueError):
            return None

    def _read_outdoor(self) -> float | None:
        """Outdoor temperature in Celsius: the weighted average of the chosen sources.

        Unavailable sources are skipped and the rest share their weight.
        """
        weights = self.config_entry.options.get(CONF_OUTDOOR_WEIGHTS, {})
        readings = {e: self._read_one_outdoor(e) for e in outdoor_sources(self.config_entry)}
        value, used = engine.weighted_mean(
            readings, {e: float(weights.get(e, 1.0)) for e in readings}
        )
        self.outdoor_used = used
        return value

    def _thermostat(self) -> State | None:
        state = self.hass.states.get(self.config_entry.data[CONF_CLIMATE])
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        return state

    # -- main loop ------------------------------------------------------------

    def _stop_retry_timer(self) -> None:
        if self._cancel_retry is not None:
            self._cancel_retry()
            self._cancel_retry = None

    async def _async_update_data(self) -> ComfortData:
        """Evaluate, and look again soon if the weather or thermostat was not there.

        After a reboot or a power cut other integrations often load later than
        this one, so waiting a whole update interval would leave the house
        unmanaged for up to an hour.
        """
        result = await self._evaluate()
        self._stop_retry_timer()
        if result.status in (STATUS_SOURCE_UNAVAILABLE, STATUS_THERMOSTAT_UNAVAILABLE):

            async def _retry(_now: datetime) -> None:
                self._cancel_retry = None
                await self.async_refresh()

            self._cancel_retry = async_call_later(self.hass, RETRY_SECONDS, _retry)
        return result

    async def _evaluate(self) -> ComfortData:
        now = dt_util.now()
        if self.windows_open and self.windows_resume_at and now >= self.windows_resume_at:
            self.windows_open = False
            self.windows_resume_at = None
            self._stop_resume_timer()
            await self._async_save()
        away = self._update_presence(now)
        opening_blocks = self._update_openings(now)
        thermostat = self._thermostat()
        safety = self._update_safety(thermostat)
        indoor_offset = self._update_indoor(thermostat, now)
        outdoor = self._read_outdoor()
        if outdoor is None and not (self.windows_open or opening_blocks or safety):
            return self._keep_last(STATUS_SOURCE_UNAVAILABLE, now)
        if thermostat is None:
            return ComfortData(STATUS_THERMOSTAT_UNAVAILABLE, outdoor, None, False, now)

        unit = self.hass.config.units.temperature_unit
        attrs = thermostat.attributes
        modes = set(attrs.get("hvac_modes") or []) or None

        def attr_c(name: str) -> float | None:
            value = attrs.get(name)
            try:
                return None if value is None else engine.to_celsius(float(value), unit)
            except (TypeError, ValueError):
                return None

        step = attrs.get("target_temp_step")
        step_c = engine.delta_to_celsius(float(step), unit) if step else 0.5

        decision: engine.Decision | None = None
        limits = safety_settings_from_options(self.config_entry.options)
        if safety and limits is not None:
            # Too hot or too cold indoors: this beats everything else.
            decision = engine.safety_decision(
                safety,
                limits,
                outdoor if outdoor is not None else 0.0,
                modes,
                min_temp=attr_c("min_temp"),
                max_temp=attr_c("max_temp"),
                step=step_c,
                range_width=float(
                    self.config_entry.options.get(CONF_RANGE_WIDTH, DEFAULT_RANGE_WIDTH)
                ),
            )
        if decision is not None:
            pass
        elif self.windows_open:
            # Windows are open: the thermostat stays off whatever the weather does.
            decision = engine.Decision(
                mode=engine.OFF,
                reason=engine.R_WINDOWS,
                outdoor=outdoor if outdoor is not None else 0.0,
            )
        elif opening_blocks:
            # A window or door is open: the thermostat stays off until all are shut.
            decision = engine.Decision(
                mode=engine.OFF,
                reason=engine.R_OPENING,
                outdoor=outdoor if outdoor is not None else 0.0,
            )
        else:
            decision = engine.decide(
                outdoor,
                now.date(),
                settings_from_options(self.config_entry.options),
                modes,
                min_temp=attr_c("min_temp"),
                max_temp=attr_c("max_temp"),
                step=step_c,
                now=now.time(),
                away=away,
            )
            decision = engine.compensate(
                decision, indoor_offset, attr_c("min_temp"), attr_c("max_temp"), step_c
            )

        is_safety = decision.reason in (engine.R_SAFETY_HOT, engine.R_SAFETY_COLD)
        if not self.enabled and not is_safety:  # safety limits ignore the pause switch
            return ComfortData(STATUS_PAUSED, outdoor, decision, False, now)
        try:
            applied = await self._apply(decision, thermostat)
        except HomeAssistantError as err:
            _LOGGER.warning("Could not update %s: %s", thermostat.entity_id, err)
            return ComfortData(STATUS_APPLY_FAILED, outdoor, decision, False, now)
        return ComfortData(decision.reason, outdoor, decision, applied, now)

    def _keep_last(self, status: str, now: datetime) -> ComfortData:
        last = self.data
        return ComfortData(
            status,
            last.outdoor if last else None,
            last.decision if last else None,
            False,
            now,
        )

    # -- driving the thermostat ----------------------------------------------

    async def _apply(self, decision: engine.Decision, thermostat: State) -> bool:
        """Send only what differs. Returns True if anything was changed."""
        unit = self.hass.config.units.temperature_unit
        entity = thermostat.entity_id
        tolerance = float(self.config_entry.options.get(CONF_MIN_CHANGE, DEFAULT_MIN_CHANGE))
        current_mode = thermostat.state
        attrs = thermostat.attributes
        changed = False

        def differs(name: str, wanted_c: float) -> bool:
            current = attrs.get(name)
            if current is None:
                return True
            try:
                current_c = engine.to_celsius(float(current), unit)
            except (TypeError, ValueError):
                return True
            return abs(current_c - wanted_c) >= tolerance - 1e-9

        if current_mode != decision.mode:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": entity, "hvac_mode": decision.mode},
                blocking=True,
            )
            changed = True

        if decision.mode == engine.OFF:
            return changed

        if decision.mode == engine.HEAT_COOL:
            if changed or differs("target_temp_low", decision.low) or differs(
                "target_temp_high", decision.high
            ):
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {
                        "entity_id": entity,
                        "target_temp_low": round(engine.from_celsius(decision.low, unit), 1),
                        "target_temp_high": round(engine.from_celsius(decision.high, unit), 1),
                    },
                    blocking=True,
                )
                changed = True
        elif changed or differs("temperature", decision.setpoint):
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {
                    "entity_id": entity,
                    "temperature": round(engine.from_celsius(decision.setpoint, unit), 1),
                },
                blocking=True,
            )
            changed = True
        return changed
