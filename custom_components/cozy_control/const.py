"""Constants and settings helpers for Cozy Control."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import engine

DOMAIN = "cozy_control"
PLATFORMS = ["sensor", "switch", "button"]

# Config entry data
CONF_WEATHER = "weather_entity"  # a weather entity or a temperature sensor
CONF_CLIMATE = "climate_entity"

# Options (all temperatures stored in Celsius)
CONF_INTERVAL = "update_interval"  # minutes
CONF_UNIT = "unit"
CONF_MIN_CHANGE = "min_change"
CONF_RANGE_WIDTH = "range_width"
CONF_INTERPOLATE = "interpolate"
CONF_SETPOINTS = "setpoints"
CONF_OFF_ENABLED = "off_enabled"
CONF_OFF_MIN = "off_min"
CONF_OFF_MAX = "off_max"
CONF_WIN_LOW = "win_low"
CONF_WIN_HIGH = "win_high"
CONF_HOT_AT = "hot_at"
CONF_COLD_AT = "cold_at"
CONF_WIN_RESUME = "win_resume"
CONF_WIN_MAX_HOURS = "win_max_hours"
CONF_USE_FORECAST = "use_forecast"
CONF_BRIEF_DATES_ENABLED = "brief_dates_enabled"
CONF_BRIEF_DATES = "brief_dates"
CONF_TIME_FORMAT = "time_format"
CONF_BED_ENABLED = "bed_enabled"
CONF_BED_START = "bed_start"
CONF_BED_END = "bed_end"
CONF_BED_SETPOINTS = "bed_setpoints"
CONF_AWAY_ENABLED = "away_enabled"
CONF_AWAY_SETPOINTS = "away_setpoints"
CONF_PRESENCE_SOURCES = "presence_sources"
CONF_PRESENCE_RADIUS = "presence_radius"
CONF_PRESENCE_DELAY = "presence_delay"
CONF_PRESENCE_MAX_ACCURACY = "presence_max_accuracy"
CONF_CONTACTS_ENABLED = "contacts_enabled"
CONF_CONTACT_SOURCES = "contact_sources"
CONF_CONTACT_DELAY = "contact_delay"
CONF_SAFETY_ENABLED = "safety_enabled"
CONF_SAFETY_HOT = "safety_hot"
CONF_SAFETY_COLD = "safety_cold"
CONF_SAFETY_SENSORS = "safety_sensors"
CONF_OUTDOOR_SOURCES = "outdoor_sources"
CONF_OUTDOOR_WEIGHTS = "outdoor_weights"
CONF_INDOOR_ENABLED = "indoor_enabled"
CONF_INDOOR_SOURCES = "indoor_sources"
CONF_INDOOR_WINDOWS = "indoor_windows"
CONF_INDOOR_WEIGHTS = "indoor_weights"
CONF_INDOOR_MAX_OFFSET = "indoor_max_offset"
CONF_HEAT_ENABLED = "heat_enabled"
CONF_COOL_ENABLED = "cool_enabled"
CONF_HEAT_DATES_ENABLED = "heat_dates_enabled"
CONF_COOL_DATES_ENABLED = "cool_dates_enabled"
CONF_HEAT_DISABLED = "heat_disabled"
CONF_COOL_DISABLED = "cool_disabled"
CONF_FEEDBACK_BURST = "feedback_burst"  # minutes: presses closer than this are one change
CONF_FEEDBACK_LIMIT = "feedback_limit"  # Celsius a row may move in a day; 0 = no limit

TIME_24H = "24h"
TIME_12H = "12h"

UNIT_SYSTEM = "system"  # follow the Home Assistant unit system
UNIT_CELSIUS = "celsius"
UNIT_FAHRENHEIT = "fahrenheit"

DEFAULT_INTERVAL = 60
DEFAULT_MIN_CHANGE = 0.5
DEFAULT_RANGE_WIDTH = 2.0
DEFAULT_SETPOINTS = [[-20.0, 23.0], [0.0, 22.0], [20.0, 20.0], [30.0, 17.0]]
DEFAULT_BED_SETPOINTS = [[-20.0, 19.0], [0.0, 18.0], [20.0, 17.0], [30.0, 17.0]]
DEFAULT_AWAY_SETPOINTS = [[-20.0, 20.0], [0.0, 19.0], [20.0, 21.0], [30.0, 21.0]]
INDOOR_WINDOW_COUNT = 2  # extra time windows with their own sensors
DEFAULT_INDOOR_WINDOW = ("20:00", "07:00")
DEFAULT_INDOOR_MAX_OFFSET = 3.0  # Celsius: the most the targets are ever shifted
DEFAULT_CONTACT_DELAY = 2  # minutes a window or door must stay open before the thermostat turns off
DEFAULT_PRESENCE_RADIUS = 150  # metres
DEFAULT_PRESENCE_DELAY = 10  # minutes everyone must be away before Away mode starts
DEFAULT_PRESENCE_MAX_ACCURACY = 200  # metres; less accurate GPS readings are ignored
DEFAULT_BED_START = "20:00"
DEFAULT_BED_END = "05:00"
DEFAULT_WIN_RESUME = "18:00"
DEFAULT_WIN_MAX_HOURS = 12
PENDING_MINUTES = 120  # how long a spoken question waits for its answer
DEFAULT_FEEDBACK_STEP = 0.5  # Celsius: how much one "I'm cold" or "I'm warm" changes
DEFAULT_FEEDBACK_BURST = 15  # minutes: presses this close together are undone together
DEFAULT_FEEDBACK_LIMIT = 2.0  # Celsius: the most one row can move in a day

PRESENCE_OPTIONS = [engine.PRESENCE_HOME, engine.PRESENCE_AWAY, engine.PRESENCE_UNKNOWN]

# Status values shown by the status sensor
STATUS_PAUSED = "paused"
STATUS_SOURCE_UNAVAILABLE = "source_unavailable"
STATUS_THERMOSTAT_UNAVAILABLE = "thermostat_unavailable"
STATUS_APPLY_FAILED = "apply_failed"
STATUS_OPTIONS = [
    engine.R_NORMAL,
    engine.R_BEDTIME,
    engine.R_AWAY,
    engine.R_WINDOWS,
    engine.R_OPENING,
    engine.R_SAFETY_HOT,
    engine.R_SAFETY_COLD,
    engine.R_OFF_RANGE,
    engine.R_BOTH_DISABLED,
    engine.R_HEAT_DISABLED,
    engine.R_COOL_DISABLED,
    STATUS_PAUSED,
    STATUS_SOURCE_UNAVAILABLE,
    STATUS_THERMOSTAT_UNAVAILABLE,
    STATUS_APPLY_FAILED,
]


def default_options() -> dict[str, Any]:
    """Options a new entry starts with."""
    return {
        CONF_INTERVAL: DEFAULT_INTERVAL,
        CONF_UNIT: UNIT_SYSTEM,
        CONF_TIME_FORMAT: TIME_24H,
        CONF_MIN_CHANGE: DEFAULT_MIN_CHANGE,
        CONF_RANGE_WIDTH: DEFAULT_RANGE_WIDTH,
        CONF_INTERPOLATE: True,
        CONF_SETPOINTS: [list(p) for p in DEFAULT_SETPOINTS],
        CONF_WIN_LOW: engine.WindowSettings.low,
        CONF_WIN_HIGH: engine.WindowSettings.high,
        CONF_HOT_AT: engine.WindowSettings.hot_at,
        CONF_COLD_AT: engine.WindowSettings.cold_at,
        CONF_WIN_RESUME: DEFAULT_WIN_RESUME,
        CONF_WIN_MAX_HOURS: DEFAULT_WIN_MAX_HOURS,
        CONF_USE_FORECAST: True,
        CONF_BRIEF_DATES_ENABLED: False,
        CONF_BRIEF_DATES: "",
        CONF_BED_ENABLED: False,
        CONF_BED_START: DEFAULT_BED_START,
        CONF_BED_END: DEFAULT_BED_END,
        CONF_BED_SETPOINTS: [list(p) for p in DEFAULT_BED_SETPOINTS],
        CONF_AWAY_ENABLED: False,
        CONF_AWAY_SETPOINTS: [list(p) for p in DEFAULT_AWAY_SETPOINTS],
        CONF_OUTDOOR_WEIGHTS: {},
        CONF_INDOOR_ENABLED: False,
        CONF_INDOOR_SOURCES: [],
        CONF_INDOOR_WINDOWS: [],
        CONF_INDOOR_WEIGHTS: {},
        CONF_INDOOR_MAX_OFFSET: DEFAULT_INDOOR_MAX_OFFSET,
        CONF_SAFETY_ENABLED: False,
        CONF_SAFETY_HOT: engine.SafetySettings.hot,
        CONF_SAFETY_COLD: engine.SafetySettings.cold,
        CONF_SAFETY_SENSORS: [],
        CONF_CONTACTS_ENABLED: False,
        CONF_CONTACT_SOURCES: [],
        CONF_CONTACT_DELAY: DEFAULT_CONTACT_DELAY,
        CONF_PRESENCE_SOURCES: [],
        CONF_PRESENCE_RADIUS: DEFAULT_PRESENCE_RADIUS,
        CONF_PRESENCE_DELAY: DEFAULT_PRESENCE_DELAY,
        CONF_PRESENCE_MAX_ACCURACY: DEFAULT_PRESENCE_MAX_ACCURACY,
        CONF_HEAT_ENABLED: True,
        CONF_COOL_ENABLED: True,
        CONF_HEAT_DISABLED: "",
        CONF_COOL_DISABLED: "",
        CONF_FEEDBACK_BURST: DEFAULT_FEEDBACK_BURST,
        CONF_FEEDBACK_LIMIT: DEFAULT_FEEDBACK_LIMIT,
    }


def display_unit(hass: HomeAssistant, options: dict[str, Any]) -> str:
    """Unit used to show and edit temperatures in the menus."""
    choice = options.get(CONF_UNIT, UNIT_SYSTEM)
    if choice == UNIT_CELSIUS:
        return engine.UNIT_C
    if choice == UNIT_FAHRENHEIT:
        return engine.UNIT_F
    return hass.config.units.temperature_unit


def dates_enabled(options: dict[str, Any], switch_key: str) -> bool:
    """Whether a "never heat/cool during" list is switched on.

    On unless switched off. Older entries have no switch stored; an empty list
    changes nothing, so on is also right for them.
    """
    return bool(options.get(switch_key, True))


def _active_dates(options: dict[str, Any], switch_key: str, dates_key: str) -> list:
    if not dates_enabled(options, switch_key):
        return []
    return engine.parse_date_ranges(options.get(dates_key, ""))


def settings_from_options(options: dict[str, Any]) -> engine.Settings:
    """Build engine settings (Celsius) from stored options."""
    points = [(float(o), float(i)) for o, i in options.get(CONF_SETPOINTS, DEFAULT_SETPOINTS)]
    off_min = options.get(CONF_OFF_MIN)
    off_max = options.get(CONF_OFF_MAX)
    # Older entries have no switch: the range counted as on whenever it was filled in.
    off_on = bool(options.get(CONF_OFF_ENABLED, off_min is not None and off_max is not None))
    bed_on = bool(options.get(CONF_BED_ENABLED, False))
    bed_points = [
        (float(o), float(i)) for o, i in options.get(CONF_BED_SETPOINTS, DEFAULT_BED_SETPOINTS)
    ]
    away_on = bool(options.get(CONF_AWAY_ENABLED, False))
    away_points = [
        (float(o), float(i)) for o, i in options.get(CONF_AWAY_SETPOINTS, DEFAULT_AWAY_SETPOINTS)
    ]
    return engine.Settings(
        setpoints=sorted(points),
        away_setpoints=sorted(away_points) if away_on else [],
        interpolate=bool(options.get(CONF_INTERPOLATE, True)),
        off_min=float(off_min) if off_on and off_min is not None else None,
        off_max=float(off_max) if off_on and off_max is not None else None,
        range_width=float(options.get(CONF_RANGE_WIDTH, DEFAULT_RANGE_WIDTH)),
        heat_disabled=_active_dates(options, CONF_HEAT_DATES_ENABLED, CONF_HEAT_DISABLED),
        cool_disabled=_active_dates(options, CONF_COOL_DATES_ENABLED, CONF_COOL_DISABLED),
        bed_setpoints=sorted(bed_points) if bed_on else [],
        bed_start=engine.parse_clock(options.get(CONF_BED_START, DEFAULT_BED_START)),
        bed_end=engine.parse_clock(options.get(CONF_BED_END, DEFAULT_BED_END)),
        heat_enabled=bool(options.get(CONF_HEAT_ENABLED, True)),
        cool_enabled=bool(options.get(CONF_COOL_ENABLED, True)),
    )


def window_settings_from_options(options: dict[str, Any]) -> engine.WindowSettings:
    """Weather limits for window advice (Celsius)."""
    d = engine.WindowSettings()
    return engine.WindowSettings(
        low=float(options.get(CONF_WIN_LOW, d.low)),
        high=float(options.get(CONF_WIN_HIGH, d.high)),
        hot_at=float(options.get(CONF_HOT_AT, d.hot_at)),
        cold_at=float(options.get(CONF_COLD_AT, d.cold_at)),
    )


def briefing_dates(options: dict[str, Any]) -> list | None:
    """Date ranges the briefing is limited to, or ``None`` for all year."""
    if not options.get(CONF_BRIEF_DATES_ENABLED, False):
        return None
    return engine.parse_date_ranges(options.get(CONF_BRIEF_DATES, "")) or None


def presence_sources(options: dict[str, Any]) -> list[str]:
    """Phones/people to watch, or an empty list when Away mode is off."""
    if not options.get(CONF_AWAY_ENABLED, False):
        return []
    return [str(e) for e in options.get(CONF_PRESENCE_SOURCES, [])]


def contact_sources(options: dict[str, Any]) -> list[str]:
    """Window and door sensors to watch, or an empty list when switched off."""
    if not options.get(CONF_CONTACTS_ENABLED, False):
        return []
    return [str(e) for e in options.get(CONF_CONTACT_SOURCES, [])]


def safety_settings_from_options(options: dict[str, Any]) -> engine.SafetySettings | None:
    """Safety limits (Celsius), or ``None`` when the safety temperatures are off."""
    if not options.get(CONF_SAFETY_ENABLED, False):
        return None
    d = engine.SafetySettings()
    return engine.SafetySettings(
        hot=float(options.get(CONF_SAFETY_HOT, d.hot)),
        cold=float(options.get(CONF_SAFETY_COLD, d.cold)),
    )


def indoor_profiles(options: dict[str, Any]) -> list[engine.IndoorProfile]:
    """Indoor sensor profiles: each time window first, then the all-day set.

    Empty when the feature is off. The thermostat's own reading is used only
    if the thermostat is in a list.
    """
    if not options.get(CONF_INDOOR_ENABLED, False):
        return []
    weights = options.get(CONF_INDOOR_WEIGHTS, {})

    def sources(entities: list[str]) -> tuple[tuple[str, float], ...]:
        return tuple((e, float(weights.get(e, 1.0))) for e in entities)

    profiles: list[engine.IndoorProfile] = []
    for window in options.get(CONF_INDOOR_WINDOWS, []):
        entities = list(window.get("sources", []))
        if not entities:
            continue
        try:
            start = engine.parse_clock(window["start"])
            end = engine.parse_clock(window["end"])
        except (KeyError, ValueError):
            continue
        profiles.append(engine.IndoorProfile(start, end, sources(entities)))
    everyday = list(options.get(CONF_INDOOR_SOURCES, []))
    if everyday:
        profiles.append(engine.IndoorProfile(None, None, sources(everyday)))
    return profiles


def outdoor_sources(entry: Any) -> list[str]:
    """Outdoor temperature sources: the chosen list, or the one picked at setup."""
    chosen = [str(e) for e in entry.options.get(CONF_OUTDOOR_SOURCES, [])]
    return chosen or [str(entry.data[CONF_WEATHER])]
