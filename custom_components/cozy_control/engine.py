"""Pure comfort logic for Cozy Control.

This module deliberately has no Home Assistant imports, so it can be tested on
its own and reused (for example by the voice assistant helpers later).

Every temperature in here is in degrees Celsius unless a name says otherwise.
The Home Assistant side converts to and from whatever unit the user prefers.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from itertools import pairwise

# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------

UNIT_C = "°C"
UNIT_F = "°F"
UNIT_K = "K"


def to_celsius(value: float, unit: str) -> float:
    """Convert a temperature reading to Celsius."""
    if unit == UNIT_F:
        return (value - 32.0) * 5.0 / 9.0
    if unit == UNIT_K:
        return value - 273.15
    return value


def from_celsius(value: float, unit: str) -> float:
    """Convert a Celsius temperature to ``unit``."""
    if unit == UNIT_F:
        return value * 9.0 / 5.0 + 32.0
    if unit == UNIT_K:
        return value + 273.15
    return value


def delta_to_celsius(delta: float, unit: str) -> float:
    """Convert a temperature *difference* (no offset) to Celsius."""
    return delta * 5.0 / 9.0 if unit == UNIT_F else delta


def delta_from_celsius(delta: float, unit: str) -> float:
    """Convert a temperature *difference* in Celsius to ``unit``."""
    return delta * 9.0 / 5.0 if unit == UNIT_F else delta


def round_to_step(value: float, step: float) -> float:
    """Round ``value`` to the nearest multiple of ``step``."""
    if step <= 0:
        return value
    return round(round(value / step) * step, 4)


# --------------------------------------------------------------------------
# Setpoint table: "outdoor: indoor" lines
# --------------------------------------------------------------------------

_NUMBER = r"[-+]?\d+(?:[.,]\d+)?"
_TABLE_LINE = re.compile(rf"^\s*({_NUMBER})\s*(?:[:=]|->|=>|\s)\s*({_NUMBER})\s*$")


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def parse_setpoints(text: str) -> list[tuple[float, float]]:
    """Parse ``outdoor: indoor`` lines into points sorted by outdoor temperature.

    Accepts one point per line or several separated by semicolons/commas.
    Numbers are returned exactly as written (the caller knows the unit).
    Raises ``ValueError`` with a readable message on bad input.
    """
    points: list[tuple[float, float]] = []
    chunks = [c for c in re.split(r"[\n;]+", text) if c.strip()]
    for chunk in chunks:
        match = _TABLE_LINE.match(chunk)
        if not match:
            raise ValueError(f"Cannot read '{chunk.strip()}'. Use the form '20: 21'.")
        points.append((_num(match.group(1)), _num(match.group(2))))
    if not points:
        raise ValueError("Add at least one outdoor: indoor pair.")
    outdoors = [p[0] for p in points]
    if len(set(outdoors)) != len(outdoors):
        raise ValueError("Each outdoor temperature can only appear once.")
    return sorted(points)


def format_setpoints(points: list[tuple[float, float]], digits: int = 1) -> str:
    """Format points as editable text, coldest outdoor temperature first."""
    return "\n".join(
        f"{_fmt(o, digits)}: {_fmt(i, digits)}" for o, i in sorted(points)
    )


def _fmt(value: float, digits: int) -> str:
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def setpoint_for(
    outdoor: float, points: list[tuple[float, float]], interpolate: bool = True
) -> float:
    """Indoor setpoint for an outdoor temperature.

    ``points`` are (outdoor, indoor) pairs in any single unit; the result is in
    the same unit. Outside the table's range the nearest end point is used.
    With ``interpolate`` the setpoint slides smoothly between points; without
    it, the point at or below the outdoor temperature applies (a step table).
    """
    if not points:
        raise ValueError("The setpoint table is empty.")
    pts = sorted(points)
    if outdoor <= pts[0][0]:
        return pts[0][1]
    if outdoor >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in pairwise(pts):
        if x0 <= outdoor <= x1:
            if not interpolate:
                return y0 if outdoor < x1 else y1
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (outdoor - x0) / (x1 - x0)
    return pts[-1][1]  # pragma: no cover - unreachable


# --------------------------------------------------------------------------
# "I'm cold" / "I'm warm": tune a table where it is wrong
# --------------------------------------------------------------------------

FEEDBACK_SNAP = 1.0  # rows are added at whole degrees (Celsius), so the table stays tidy
FEEDBACK_MIN = 10.0  # a nudged row never goes below or above these (Celsius)
FEEDBACK_MAX = 30.0


def nudge_setpoints(
    points: list[tuple[float, float]],
    outdoor: float,
    delta: float,
    interpolate: bool = True,
    snap: float = FEEDBACK_SNAP,
    low: float = FEEDBACK_MIN,
    high: float = FEEDBACK_MAX,
) -> tuple[list[tuple[float, float]], float, float, float]:
    """Make the table ``delta`` warmer (or cooler, if negative) at ``outdoor``.

    The outdoor temperature is rounded to ``snap``. A row already there is
    moved; otherwise a row is added there, at what the table gave plus
    ``delta``. Rows around it are untouched, so with a sliding table the change
    fades out towards the neighbouring rows, and the rest of the table stays as
    it was. The result is kept within ``low`` and ``high`` (and always within
    FEEDBACK_MIN and FEEDBACK_MAX) and rounded to 0.1. A row already outside
    those limits is never pulled back by a change in the other direction: it
    just doesn't move.

    Returns (new points, the row's outdoor temperature, old indoor, new indoor).
    """
    if not points:
        raise ValueError("The setpoint table is empty.")
    at = round_to_step(outdoor, snap)
    pts = sorted(points)
    for x, y in pts:
        if abs(x - at) < 1e-6:
            old = y
            break
    else:
        old = setpoint_for(at, pts, interpolate)
    low = max(FEEDBACK_MIN, low)
    high = min(FEEDBACK_MAX, high)
    if delta > 0:
        new = old if old >= high else min(high, old + delta)
    else:
        new = old if old <= low else max(low, old + delta)
    new = round(new, 1)
    if abs(new - round(old, 1)) < 1e-9:
        return sorted(points), at, round(old, 1), round(old, 1)
    result = [(x, y) for x, y in pts if abs(x - at) >= 1e-6]
    result.append((at, new))
    return sorted(result), at, round(old, 1), new


# --------------------------------------------------------------------------
# Date windows for "heat/AC disabled" seasons
# --------------------------------------------------------------------------

MonthDay = tuple[int, int]
DateRange = tuple[MonthDay, MonthDay]

_RANGE = re.compile(
    r"^\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*(?:to|until|through|\.\.|–|—|-)\s*"
    r"(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*$",
    re.IGNORECASE,
)
_DAYS_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _month_day(month: int, day: int, original: str) -> MonthDay:
    if not 1 <= month <= 12 or not 1 <= day <= _DAYS_IN_MONTH[month - 1]:
        raise ValueError(f"'{original}' is not a real date (use MM-DD).")
    return (month, day)


def parse_date_ranges(text: str) -> list[DateRange]:
    """Parse ranges like ``06-01 to 08-31``, one per line or comma separated.

    The year is ignored, so a range repeats every year, and a range may wrap
    around New Year (``11-01 to 02-28``). Empty text means no ranges.
    """
    ranges: list[DateRange] = []
    for chunk in re.split(r"[\n,;]+", text or ""):
        if not chunk.strip():
            continue
        match = _RANGE.match(chunk)
        if not match:
            raise ValueError(f"Cannot read '{chunk.strip()}'. Use the form '06-01 to 08-31'.")
        m1, d1, m2, d2 = (int(g) for g in match.groups())
        ranges.append(
            (_month_day(m1, d1, chunk.strip()), _month_day(m2, d2, chunk.strip()))
        )
    return ranges


def format_date_ranges(ranges: list[DateRange]) -> str:
    """Format ranges as editable text, one per line."""
    return "\n".join(
        f"{a[0]:02d}-{a[1]:02d} to {b[0]:02d}-{b[1]:02d}" for a, b in ranges
    )


def in_date_ranges(today: date, ranges: list[DateRange]) -> bool:
    """True when ``today`` falls inside any of the (yearly repeating) ranges."""
    now: MonthDay = (today.month, today.day)
    for start, end in ranges:
        if start <= end:
            if start <= now <= end:
                return True
        elif now >= start or now <= end:  # wraps over New Year
            return True
    return False


# --------------------------------------------------------------------------
# Time of day (bedtime window)
# --------------------------------------------------------------------------

_CLOCK = re.compile(
    r"^\s*(\d{1,2})(?:\s*:\s*(\d{2}))?(?:\s*:\s*\d{2})?\s*([ap])\.?\s*m?\.?\s*$|"
    r"^\s*(\d{1,2})\s*:\s*(\d{2})(?:\s*:\s*\d{2})?\s*$",
    re.IGNORECASE,
)


def parse_clock(text: str) -> time:
    """Parse a time of day: ``20:00``, ``8:00 PM``, ``8pm`` or ``8 a.m.``.

    Seconds are ignored. With AM/PM the hour must be 1-12 (12 AM is midnight,
    12 PM is noon); without it the hour is 0-23.
    """
    match = _CLOCK.match(text or "")
    if match:
        if match.group(3):  # 12 hour with am/pm
            hour, minute = int(match.group(1)), int(match.group(2) or 0)
            if 1 <= hour <= 12 and minute <= 59:
                hour = hour % 12 + (12 if match.group(3).lower() == "p" else 0)
                return time(hour, minute)
        else:
            hour, minute = int(match.group(4)), int(match.group(5))
            if hour <= 23 and minute <= 59:
                return time(hour, minute)
    raise ValueError(f"'{(text or '').strip()}' is not a time of day (use 20:00 or 8:00 PM).")


def format_clock(value: time, hour12: bool = False) -> str:
    """Format a time of day as ``20:00``, or ``8:00 PM`` with ``hour12``."""
    if not hour12:
        return f"{value.hour:02d}:{value.minute:02d}"
    suffix = "AM" if value.hour < 12 else "PM"
    return f"{value.hour % 12 or 12}:{value.minute:02d} {suffix}"


def in_time_window(now: time, start: time, end: time) -> bool:
    """True when ``now`` is in [start, end). A window may cross midnight.

    Equal start and end mean an empty window (never), not all day.
    """
    if start == end:
        return False
    now = now.replace(second=0, microsecond=0)
    if start < end:
        return start <= now < end
    return now >= start or now < end


# --------------------------------------------------------------------------
# Presence: are we home?
# --------------------------------------------------------------------------

PRESENCE_HOME = "home"
PRESENCE_AWAY = "away"
PRESENCE_UNKNOWN = "unknown"

_EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two latitude/longitude points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


@dataclass(frozen=True)
class SourceReading:
    """What one phone or person says about being home."""

    home: bool | None  # None: no usable reading
    distance_m: float | None = None


def read_source(
    state: str | None,
    latitude: float | None,
    longitude: float | None,
    accuracy: float | None,
    home_lat: float,
    home_lon: float,
    radius_m: float,
    max_accuracy_m: float,
) -> SourceReading:
    """Decide whether one source is home.

    With a GPS position the distance to home is compared with ``radius_m``. A
    position whose accuracy is worse than ``max_accuracy_m`` is ignored (a bad
    fix is how phones appear to jump away from home and back), as are
    unavailable sources. Without a position, the tracker's own state is used:
    ``home`` is home, ``not_home`` or any other zone is away.
    """
    if state is None or state in ("unknown", "unavailable"):
        return SourceReading(None)
    if latitude is not None and longitude is not None:
        if accuracy is not None and accuracy > max_accuracy_m:
            return SourceReading(None)
        distance = haversine_m(latitude, longitude, home_lat, home_lon)
        return SourceReading(distance <= radius_m, round(distance, 1))
    if state == "home":
        return SourceReading(True)
    return SourceReading(False)


def combine_presence(readings: list[SourceReading]) -> str:
    """Home if anyone is home, away only if everyone with a reading is away.

    No usable reading at all is "unknown", which never counts as away.
    """
    known = [r.home for r in readings if r.home is not None]
    if not known:
        return PRESENCE_UNKNOWN
    return PRESENCE_HOME if any(known) else PRESENCE_AWAY


def held_for(since: datetime | None, now: datetime, minutes: float) -> bool:
    """True once something that began at ``since`` has lasted ``minutes``."""
    return since is not None and now - since >= timedelta(minutes=minutes)


def away_confirmed(
    away_since: datetime | None, now: datetime, delay_minutes: float
) -> bool:
    """True once everyone has been away for the whole delay."""
    return held_for(away_since, now, delay_minutes)


# --------------------------------------------------------------------------
# Decision
# --------------------------------------------------------------------------

HEAT = "heat"
COOL = "cool"
HEAT_COOL = "heat_cool"
OFF = "off"

# Reasons are stable keys (translated in the UI).
R_NORMAL = "following_curve"
R_BEDTIME = "following_bedtime_table"
R_AWAY = "following_away_table"
R_OPENING = "door_or_window_open"
R_SAFETY_HOT = "safety_too_hot"
R_SAFETY_COLD = "safety_too_cold"
R_WINDOWS = "windows_open"
R_OFF_RANGE = "outdoor_in_off_range"
R_BOTH_DISABLED = "heating_and_cooling_disabled"
R_HEAT_DISABLED = "heating_disabled_by_date"
R_COOL_DISABLED = "cooling_disabled_by_date"


@dataclass(frozen=True)
class Settings:
    """User settings, all temperatures in Celsius."""

    setpoints: list[tuple[float, float]]
    interpolate: bool = True
    off_min: float | None = None
    off_max: float | None = None
    range_width: float = 2.0
    heat_disabled: list[DateRange] = field(default_factory=list)
    cool_disabled: list[DateRange] = field(default_factory=list)
    heat_enabled: bool = True  # master switches, independent of the date ranges
    cool_enabled: bool = True
    # Bedtime: its own table, used between bed_start and bed_end each day.
    bed_setpoints: list[tuple[float, float]] = field(default_factory=list)
    bed_start: time | None = None
    bed_end: time | None = None
    # Away: its own table, used while nobody is home (empty: no away mode).
    away_setpoints: list[tuple[float, float]] = field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    """What the thermostat should be doing right now."""

    mode: str
    reason: str
    outdoor: float
    setpoint: float | None = None  # single target (heat or cool)
    low: float | None = None  # heat_cool range
    high: float | None = None
    heat_allowed: bool = True
    cool_allowed: bool = True
    bedtime: bool = False  # the bedtime table was used
    away: bool = False  # the away table was used
    offset: float = 0.0  # indoor sensor compensation already added to the targets


def decide(
    outdoor: float,
    today: date,
    settings: Settings,
    supported_modes: set[str] | None = None,
    min_temp: float | None = None,
    max_temp: float | None = None,
    step: float = 0.5,
    now: time | None = None,
    away: bool = False,
) -> Decision:
    """Work out the thermostat mode and target for the current conditions.

    ``supported_modes`` are the thermostat's HVAC modes; ``None`` means unknown
    and everything is assumed to be available. ``min_temp``/``max_temp`` are the
    thermostat's limits in Celsius, and ``step`` its target step in Celsius.
    ``now`` is the local time of day; it selects the bedtime table when inside
    the bedtime window (leave it out to never use the bedtime table). ``away``
    means nobody is home: the away table is used instead, and wins over bedtime.
    """
    modes = supported_modes
    can_heat = modes is None or HEAT in modes or HEAT_COOL in modes
    can_cool = modes is None or COOL in modes or HEAT_COOL in modes
    can_range = modes is None or HEAT_COOL in modes

    heat_blocked = not settings.heat_enabled or in_date_ranges(today, settings.heat_disabled)
    cool_blocked = not settings.cool_enabled or in_date_ranges(today, settings.cool_disabled)
    heat_ok = can_heat and not heat_blocked
    cool_ok = can_cool and not cool_blocked
    heat_blocked_by_date = heat_blocked
    cool_blocked_by_date = cool_blocked

    use_away = bool(away and settings.away_setpoints)
    bedtime = bool(
        not use_away
        and now is not None
        and settings.bed_setpoints
        and settings.bed_start is not None
        and settings.bed_end is not None
        and in_time_window(now, settings.bed_start, settings.bed_end)
    )
    normal = R_AWAY if use_away else (R_BEDTIME if bedtime else R_NORMAL)

    def build(mode: str, reason: str, **kw: float | None) -> Decision:
        return Decision(
            mode=mode,
            reason=reason,
            outdoor=outdoor,
            heat_allowed=heat_ok,
            cool_allowed=cool_ok,
            bedtime=bedtime,
            away=use_away,
            **kw,
        )

    # 1. Mild enough outside: switch the thermostat off.
    if (
        settings.off_min is not None
        and settings.off_max is not None
        and settings.off_min <= outdoor <= settings.off_max
    ):
        return build(OFF, R_OFF_RANGE)

    # 2. Nothing is allowed to run.
    if not heat_ok and not cool_ok:
        return build(OFF, R_BOTH_DISABLED)

    table = (
        settings.away_setpoints
        if use_away
        else (settings.bed_setpoints if bedtime else settings.setpoints)
    )
    raw = setpoint_for(outdoor, table, settings.interpolate)

    def clamp(value: float) -> float:
        if min_temp is not None:
            value = max(value, min_temp)
        if max_temp is not None:
            value = min(value, max_temp)
        return round_to_step(value, step)

    target = clamp(raw)

    # 3. Only one of heat/cool is allowed.
    if heat_ok and not cool_ok:
        reason = R_COOL_DISABLED if cool_blocked_by_date else normal
        return build(HEAT, reason, setpoint=target)
    if cool_ok and not heat_ok:
        reason = R_HEAT_DISABLED if heat_blocked_by_date else normal
        return build(COOL, reason, setpoint=target)

    # 4. Both allowed: a range if the thermostat supports it.
    if can_range:
        half = max(settings.range_width, step) / 2.0
        low = clamp(raw - half)
        high = clamp(raw + half)
        if high - low < step:  # clamped against a limit: keep a minimal gap
            if high + step <= (max_temp if max_temp is not None else high + step):
                high = round_to_step(low + step, step)
            else:
                low = round_to_step(high - step, step)
        return build(HEAT_COOL, normal, low=low, high=high)

    # No range mode: pick heat or cool from the outdoor temperature.
    if outdoor < raw:
        return build(HEAT, normal, setpoint=target)
    return build(COOL, normal, setpoint=target)


# --------------------------------------------------------------------------
# Windows: advice for the day and when to resume
# --------------------------------------------------------------------------

ADVICE_OPEN = "open_windows"
ADVICE_CLOSED_HEAT = "keep_closed_heat"
ADVICE_CLOSED_AC = "keep_closed_ac"

# What a "yes" or "no" answer does to a question.
ACT_NONE = "none"
ACT_OPEN = "open"  # treat the windows as open: thermostat off until the resume time


@dataclass(frozen=True)
class WindowSettings:
    """Weather limits for window advice, in Celsius."""

    low: float = 18.0  # at or above this daily high, opening windows is pleasant
    high: float = 23.0  # at or below this daily high, opening windows is pleasant
    hot_at: float = 30.0  # at or above: the AC is advisable
    cold_at: float = 8.0  # at or below: heating is advisable


@dataclass(frozen=True)
class Advice:
    """What to tell the person, and what their answer would do."""

    kind: str
    message: str
    question: str | None = None
    yes_action: str = ACT_NONE
    no_action: str = ACT_NONE


def say_temperature(celsius: float, unit: str) -> str:
    """A temperature as it would be spoken, in the person's unit."""
    return f"{round(from_celsius(celsius, unit))} degrees"


def advise(
    high: float | None,
    low: float | None,
    current: float,
    limits: WindowSettings,
    thermostat_running: bool,
    unit: str = UNIT_C,
    resume_text: str = "this evening",
) -> Advice:
    """Advice about windows and the thermostat for today.

    ``high``/``low`` are today's forecast (``None`` when there is no forecast, in
    which case the current temperature stands in for both).
    """
    have_forecast = high is not None
    day_high = high if high is not None else current
    if have_forecast and low is not None:
        weather = (
            f"Today's forecast is a high of {say_temperature(day_high, unit)} "
            f"and a low of {say_temperature(low, unit)}."
        )
    elif have_forecast:
        weather = f"Today's forecast is a high of {say_temperature(day_high, unit)}."
    else:
        weather = f"It is {say_temperature(current, unit)} outside right now."

    if limits.low <= day_high <= limits.high:
        if thermostat_running:
            return Advice(
                ADVICE_OPEN,
                f"{weather} It is a good day to open the windows.",
                f"Would you like me to turn the thermostat off until {resume_text}?",
                yes_action=ACT_OPEN,
                no_action=ACT_NONE,
            )
        return Advice(
            ADVICE_OPEN,
            f"{weather} It is a good day to open the windows, and the thermostat is already off.",
        )

    if day_high < limits.low:
        if day_high <= limits.cold_at:
            tip = "It is going to be cold. It is advisable to keep the heat on and the windows closed."
        else:
            tip = "It is going to be cool. It is best to keep the windows closed."
        kind = ADVICE_CLOSED_HEAT
    else:
        if day_high >= limits.hot_at:
            tip = "It is going to be hot. It is advisable to run the AC and keep the windows closed."
        else:
            tip = "It is going to be warm. It is best to keep the windows closed to hold the cool air in."
        kind = ADVICE_CLOSED_AC
    return Advice(
        kind,
        f"{weather} {tip}",
        "Will you be leaving the windows closed today?",
        yes_action=ACT_NONE,
        no_action=ACT_OPEN,
    )


def next_resume(
    now: datetime, at: time | None = None, max_hours: float = 0.0
) -> datetime | None:
    """When the thermostat should come back on after the windows were opened.

    ``at`` is a time of day: the next time it comes round (today if it is still
    ahead, otherwise tomorrow). ``max_hours`` is a safety cap counted from ``now``
    (0 means no cap). The earlier of the two wins; ``None`` means no limit.
    """
    candidates: list[datetime] = []
    if at is not None:
        target = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        candidates.append(target)
    if max_hours and max_hours > 0:
        candidates.append(now + timedelta(hours=max_hours))
    return min(candidates) if candidates else None


# --------------------------------------------------------------------------
# Safety temperatures (indoor only)
# --------------------------------------------------------------------------

SAFETY_HOT = "hot"
SAFETY_COLD = "cold"


@dataclass(frozen=True)
class SafetySettings:
    """Indoor temperatures at which the house is kept safe whatever else is set."""

    hot: float = 30.0  # at or above this indoors: cool
    cold: float = 10.0  # at or below this indoors: heat
    margin: float = 2.0  # how far back from a limit it has to recover before releasing


def safety_state(
    hottest: float | None,
    coldest: float | None,
    limits: SafetySettings,
    active: str | None = None,
) -> str | None:
    """Whether the indoor temperature calls for emergency cooling or heating.

    ``hottest`` and ``coldest`` are the extremes over every indoor reading
    (``None`` when there are none). Once a limit has been hit, the safety
    action is held until the temperature has recovered by the margin, so the
    thermostat does not flip on and off around the limit.
    """
    if hottest is not None and hottest >= limits.hot:
        return SAFETY_HOT
    if coldest is not None and coldest <= limits.cold:
        return SAFETY_COLD
    if active == SAFETY_HOT and hottest is not None and hottest > limits.hot - limits.margin:
        return SAFETY_HOT
    if active == SAFETY_COLD and coldest is not None and coldest < limits.cold + limits.margin:
        return SAFETY_COLD
    return None


def safety_decision(
    kind: str,
    limits: SafetySettings,
    outdoor: float,
    supported_modes: set[str] | None = None,
    min_temp: float | None = None,
    max_temp: float | None = None,
    step: float = 0.5,
    range_width: float = 2.0,
) -> Decision | None:
    """The thermostat setting for a safety situation, or ``None`` if it cannot do it.

    Hot: cool until the temperature is back at the hot limit minus the margin.
    Cold: heat until it is back at the cold limit plus the margin.
    """
    modes = supported_modes
    hot = kind == SAFETY_HOT
    single = COOL if hot else HEAT
    reason = R_SAFETY_HOT if hot else R_SAFETY_COLD
    target = limits.hot - limits.margin if hot else limits.cold + limits.margin
    if min_temp is not None:
        target = max(target, min_temp)
    if max_temp is not None:
        target = min(target, max_temp)
    target = round_to_step(target, step)
    common = {"outdoor": outdoor, "heat_allowed": True, "cool_allowed": True}
    if modes is None or single in modes:
        return Decision(mode=single, reason=reason, setpoint=target, **common)
    if HEAT_COOL in modes:
        width = max(range_width, step)
        low, high = (round_to_step(target - width, step), target) if hot else (
            target,
            round_to_step(target + width, step),
        )
        return Decision(mode=HEAT_COOL, reason=reason, low=low, high=high, **common)
    return None


# --------------------------------------------------------------------------
# Indoor temperature sources: weighted sensors that can change through the day
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class IndoorProfile:
    """Which sensors to average, and when. No window means all day."""

    start: time | None
    end: time | None
    sources: tuple[tuple[str, float], ...]  # (entity id, weight)


def active_indoor_profile(profiles: list[IndoorProfile], now: time) -> IndoorProfile | None:
    """The profile for this time of day: the first window that matches, else the all-day line."""
    for profile in profiles:
        if (
            profile.start is not None
            and profile.end is not None
            and in_time_window(now, profile.start, profile.end)
        ):
            return profile
    return next((p for p in profiles if p.start is None), None)


def weighted_mean(
    readings: dict[str, float | None], weights: dict[str, float]
) -> tuple[float | None, dict[str, float]]:
    """Weighted average of the readings that exist, and the weights actually used.

    Sources without a reading (unavailable sensors) are skipped and the others
    share the weight, so one dead sensor never breaks the average.
    """
    total = weighted = 0.0
    used: dict[str, float] = {}
    for name, value in readings.items():
        weight = weights.get(name, 1.0)
        if weight <= 0 or value is None:
            continue
        total += weight
        weighted += weight * value
        used[name] = weight
    if total <= 0:
        return None, {}
    return weighted / total, used


def weighted_average(
    readings: dict[str, float | None], profile: IndoorProfile
) -> tuple[float | None, dict[str, float]]:
    """Weighted average over the sources of one indoor profile."""
    return weighted_mean(
        {name: readings.get(name) for name, _ in profile.sources}, dict(profile.sources)
    )


def compensate(
    decision: Decision,
    offset: float,
    min_temp: float | None = None,
    max_temp: float | None = None,
    step: float = 0.5,
) -> Decision:
    """Shift the thermostat targets so the chosen sensors reach the wanted temperature.

    The thermostat steers by its own reading. If that reads ``offset`` warmer
    than the sensors do, asking it for ``offset`` more makes the sensors reach
    the temperature actually wanted.
    """
    if decision.mode == OFF or offset == 0:
        return decision

    def shift(value: float | None) -> float | None:
        if value is None:
            return None
        value += offset
        if min_temp is not None:
            value = max(value, min_temp)
        if max_temp is not None:
            value = min(value, max_temp)
        return round_to_step(value, step)

    low, high = shift(decision.low), shift(decision.high)
    if low is not None and high is not None and high - low < step:
        if max_temp is None or low + step <= max_temp:
            high = round_to_step(low + step, step)
        else:
            low = round_to_step(high - step, step)
    return replace(decision, setpoint=shift(decision.setpoint), low=low, high=high, offset=offset)
