"""Tests for the pure comfort engine (no Home Assistant needed)."""

import importlib.util
import pathlib
import sys
from datetime import UTC, date, datetime, time

import pytest

_path = pathlib.Path(__file__).parents[1] / "custom_components/cozy_control/engine.py"
_spec = importlib.util.spec_from_file_location("engine", _path)
e = importlib.util.module_from_spec(_spec)
sys.modules["engine"] = e
_spec.loader.exec_module(e)

EXAMPLE = [(-20.0, 23.0), (0.0, 22.0), (20.0, 20.0), (30.0, 17.0)]


def make(**kw):
    return e.Settings(setpoints=EXAMPLE, **kw)


# ---- units ----------------------------------------------------------------


def test_unit_round_trip():
    assert e.to_celsius(68, e.UNIT_F) == pytest.approx(20.0)
    assert e.from_celsius(20, e.UNIT_F) == pytest.approx(68.0)
    assert e.to_celsius(293.15, e.UNIT_K) == pytest.approx(20.0)
    assert e.delta_to_celsius(1.8, e.UNIT_F) == pytest.approx(1.0)
    assert e.delta_from_celsius(1.0, e.UNIT_F) == pytest.approx(1.8)


def test_round_to_step():
    assert e.round_to_step(20.26, 0.5) == 20.5
    assert e.round_to_step(20.24, 0.5) == 20.0
    assert e.round_to_step(20.3, 0) == 20.3


# ---- setpoint table -------------------------------------------------------


def test_parse_setpoints_sorted_and_flexible():
    text = "30: 17\n0 = 22\n-20 -> 23\n20 20"
    assert e.parse_setpoints(text) == [(-20, 23), (0, 22), (20, 20), (30, 17)]


def test_parse_setpoints_decimal_comma_and_semicolons():
    assert e.parse_setpoints("10,5: 21,5; 20: 20") == [(10.5, 21.5), (20.0, 20.0)]


@pytest.mark.parametrize("bad", ["", "   ", "hot: cold", "20: 20\n20: 21"])
def test_parse_setpoints_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        e.parse_setpoints(bad)


def test_format_setpoints_round_trip():
    text = e.format_setpoints(EXAMPLE)
    assert text == "-20: 23\n0: 22\n20: 20\n30: 17"
    assert e.parse_setpoints(text) == EXAMPLE


@pytest.mark.parametrize(
    "outdoor,expected",
    [
        (-40, 23),  # colder than table: end point
        (-20, 23),
        (-10, 22.5),  # halfway between -20 and 0
        (0, 22),
        (10, 21),
        (20, 20),
        (25, 18.5),
        (30, 17),
        (45, 17),  # hotter than table: end point
    ],
)
def test_setpoint_interpolates(outdoor, expected):
    assert e.setpoint_for(outdoor, EXAMPLE) == pytest.approx(expected)


def test_setpoint_step_mode_uses_point_at_or_below():
    assert e.setpoint_for(10, EXAMPLE, interpolate=False) == 22
    assert e.setpoint_for(20, EXAMPLE, interpolate=False) == 20
    assert e.setpoint_for(29.9, EXAMPLE, interpolate=False) == 20
    assert e.setpoint_for(30, EXAMPLE, interpolate=False) == 17


def test_single_point_table_is_constant():
    assert e.setpoint_for(-5, [(10, 21)]) == 21
    assert e.setpoint_for(50, [(10, 21)]) == 21


# ---- date ranges ----------------------------------------------------------


def test_parse_date_ranges_formats():
    assert e.parse_date_ranges("06-01 to 08-31") == [((6, 1), (8, 31))]
    assert e.parse_date_ranges("6/1 - 8/31, 11-01 until 02-28") == [
        ((6, 1), (8, 31)),
        ((11, 1), (2, 28)),
    ]
    assert e.parse_date_ranges("") == []
    assert e.parse_date_ranges(None) == []


@pytest.mark.parametrize("bad", ["June to August", "13-01 to 14-01", "02-30 to 03-01", "06-01"])
def test_parse_date_ranges_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        e.parse_date_ranges(bad)


def test_format_date_ranges_round_trip():
    ranges = [((6, 1), (8, 31)), ((11, 1), (2, 28))]
    assert e.parse_date_ranges(e.format_date_ranges(ranges)) == ranges


def test_in_date_ranges_plain_and_wrapping():
    summer = e.parse_date_ranges("06-01 to 08-31")
    assert e.in_date_ranges(date(2026, 6, 1), summer)
    assert e.in_date_ranges(date(2026, 8, 31), summer)
    assert not e.in_date_ranges(date(2026, 9, 1), summer)
    assert not e.in_date_ranges(date(2026, 5, 31), summer)
    winter = e.parse_date_ranges("11-01 to 02-28")
    assert e.in_date_ranges(date(2026, 12, 25), winter)
    assert e.in_date_ranges(date(2027, 1, 15), winter)
    assert e.in_date_ranges(date(2027, 2, 28), winter)
    assert not e.in_date_ranges(date(2027, 3, 1), winter)
    assert not e.in_date_ranges(date(2026, 10, 31), winter)
    assert not e.in_date_ranges(date(2026, 7, 4), [])


# ---- decisions ------------------------------------------------------------

WINTER_DAY = date(2026, 1, 15)
SUMMER_DAY = date(2026, 7, 15)


def test_decide_follows_curve_with_range_when_supported():
    d = e.decide(10, WINTER_DAY, make(), {"off", "heat", "cool", "heat_cool"})
    assert d.mode == e.HEAT_COOL
    assert d.low == 20.0 and d.high == 22.0  # 21 +/- 1
    assert d.reason == e.R_NORMAL


def test_decide_without_range_mode_picks_heat_or_cool():
    modes = {"off", "heat", "cool"}
    cold = e.decide(0, WINTER_DAY, make(), modes)
    assert (cold.mode, cold.setpoint) == (e.HEAT, 22.0)
    hot = e.decide(30, SUMMER_DAY, make(), modes)
    assert (hot.mode, hot.setpoint) == (e.COOL, 17.0)


def test_decide_off_range():
    s = make(off_min=19, off_max=21)
    assert e.decide(20, WINTER_DAY, s).mode == e.OFF
    assert e.decide(20, WINTER_DAY, s).reason == e.R_OFF_RANGE
    assert e.decide(19, WINTER_DAY, s).mode == e.OFF
    assert e.decide(21, WINTER_DAY, s).mode == e.OFF
    assert e.decide(21.1, WINTER_DAY, s).mode != e.OFF
    assert e.decide(18.9, WINTER_DAY, s).mode != e.OFF


def test_decide_ignores_half_defined_off_range():
    assert e.decide(20, WINTER_DAY, make(off_min=19)).mode != e.OFF


def test_decide_heat_disabled_by_date_uses_cool_only():
    s = make(heat_disabled=e.parse_date_ranges("06-01 to 08-31"))
    d = e.decide(30, SUMMER_DAY, s, {"off", "heat", "cool", "heat_cool"})
    assert d.mode == e.COOL and not d.heat_allowed and d.reason == e.R_HEAT_DISABLED
    # outside the window, heat is back
    d2 = e.decide(30, WINTER_DAY, s, {"off", "heat", "cool", "heat_cool"})
    assert d2.mode == e.HEAT_COOL


def test_decide_cool_disabled_by_date_uses_heat_only():
    s = make(cool_disabled=e.parse_date_ranges("11-01 to 03-01"))
    d = e.decide(0, WINTER_DAY, s, {"off", "heat", "cool", "heat_cool"})
    assert d.mode == e.HEAT and d.setpoint == 22.0 and d.reason == e.R_COOL_DISABLED


def test_decide_both_disabled_turns_off():
    rng = e.parse_date_ranges("01-01 to 12-31")
    d = e.decide(5, WINTER_DAY, make(heat_disabled=rng, cool_disabled=rng))
    assert d.mode == e.OFF and d.reason == e.R_BOTH_DISABLED


def test_decide_heating_switched_off_uses_cool_only():
    d = e.decide(30, WINTER_DAY, make(heat_enabled=False), {"off", "heat", "cool", "heat_cool"})
    assert d.mode == e.COOL and not d.heat_allowed


def test_decide_cooling_switched_off_uses_heat_only():
    d = e.decide(0, SUMMER_DAY, make(cool_enabled=False), {"off", "heat", "cool", "heat_cool"})
    assert d.mode == e.HEAT and d.setpoint == 22.0 and not d.cool_allowed


def test_decide_both_switched_off_turns_off():
    d = e.decide(5, WINTER_DAY, make(heat_enabled=False, cool_enabled=False))
    assert d.mode == e.OFF and d.reason == e.R_BOTH_DISABLED


def test_decide_thermostat_without_cooling_only_heats():
    d = e.decide(30, SUMMER_DAY, make(), {"off", "heat"})
    assert d.mode == e.HEAT and not d.cool_allowed
    assert d.reason == e.R_NORMAL  # not blocked by a date, just unsupported


def test_decide_clamps_to_thermostat_limits_and_step():
    d = e.decide(-20, WINTER_DAY, make(), {"heat", "cool"}, min_temp=9, max_temp=22, step=0.5)
    assert d.setpoint == 22.0  # curve says 23, thermostat tops out at 22
    d2 = e.decide(10, WINTER_DAY, make(), {"heat", "cool"}, step=1.0)
    assert d2.setpoint == 21.0


def test_decide_range_keeps_minimal_gap_at_limit():
    d = e.decide(-20, WINTER_DAY, make(), {"heat_cool"}, min_temp=9, max_temp=22, step=0.5)
    assert d.mode == e.HEAT_COOL
    assert d.high - d.low >= 0.5
    assert d.high <= 22.0 and d.low >= 9.0


# ---- bedtime ---------------------------------------------------------------

BED = [(-20.0, 19.0), (0.0, 18.0), (20.0, 17.0)]


def bedtime_settings(**kw):
    return make(bed_setpoints=BED, bed_start=time(20, 0), bed_end=time(5, 0), **kw)


def test_parse_clock_accepts_and_rejects():
    assert e.parse_clock("20:00") == time(20, 0)
    assert e.parse_clock("5:30") == time(5, 30)
    assert e.parse_clock("20:00:00") == time(20, 0)
    for bad in ("24:00", "12:60", "evening", ""):
        with pytest.raises(ValueError):
            e.parse_clock(bad)
    assert e.format_clock(time(5, 7)) == "05:07"


def test_time_window_crossing_midnight():
    start, end = time(20, 0), time(5, 0)
    assert e.in_time_window(time(20, 0), start, end)
    assert e.in_time_window(time(23, 59), start, end)
    assert e.in_time_window(time(0, 0), start, end)
    assert e.in_time_window(time(4, 59), start, end)
    assert not e.in_time_window(time(5, 0), start, end)
    assert not e.in_time_window(time(12, 0), start, end)
    assert not e.in_time_window(time(19, 59), start, end)


def test_time_window_same_day_and_empty():
    assert e.in_time_window(time(13, 0), time(12, 0), time(14, 0))
    assert not e.in_time_window(time(14, 0), time(12, 0), time(14, 0))
    assert not e.in_time_window(time(12, 0), time(12, 0), time(12, 0))


def test_decide_uses_bedtime_table_inside_window():
    s = bedtime_settings()
    night = e.decide(20, WINTER_DAY, s, now=time(22, 0))
    assert night.bedtime and night.reason == e.R_BEDTIME
    assert night.low is not None and abs((night.low + night.high) / 2 - 17.0) <= 0.5
    cold = e.decide(0, WINTER_DAY, s, {"heat"}, now=time(3, 0))
    assert cold.mode == e.HEAT and cold.setpoint == 18.0 and cold.bedtime


def test_decide_uses_day_table_outside_window_or_without_time():
    s = bedtime_settings()
    day = e.decide(0, WINTER_DAY, s, {"heat"}, now=time(12, 0))
    assert day.setpoint == 22.0 and not day.bedtime and day.reason == e.R_NORMAL
    unknown = e.decide(0, WINTER_DAY, s, {"heat"})
    assert unknown.setpoint == 22.0 and not unknown.bedtime


def test_decide_bedtime_still_respects_off_range_and_limits():
    s = bedtime_settings(off_min=19, off_max=21)
    assert e.decide(20, WINTER_DAY, s, now=time(22, 0)).mode == e.OFF
    d = e.decide(-20, WINTER_DAY, bedtime_settings(), {"heat"}, max_temp=18, now=time(22, 0))
    assert d.setpoint == 18.0


def test_parse_clock_twelve_hour_forms():
    assert e.parse_clock("8pm") == time(20, 0)
    assert e.parse_clock("8:00 PM") == time(20, 0)
    assert e.parse_clock("8:30 p.m.") == time(20, 30)
    assert e.parse_clock("5 AM") == time(5, 0)
    assert e.parse_clock("12 AM") == time(0, 0)
    assert e.parse_clock("12:15 am") == time(0, 15)
    assert e.parse_clock("12 PM") == time(12, 0)
    assert e.parse_clock("11:59 pm") == time(23, 59)
    for bad in ("0 AM", "13 PM", "20:00 PM", "8:60 PM", "8 XM"):
        with pytest.raises(ValueError):
            e.parse_clock(bad)


def test_format_clock_both_styles_round_trip():
    for hour in range(24):
        for minute in (0, 5, 59):
            t = time(hour, minute)
            assert e.parse_clock(e.format_clock(t)) == t
            assert e.parse_clock(e.format_clock(t, hour12=True)) == t
    assert e.format_clock(time(20, 0), hour12=True) == "8:00 PM"
    assert e.format_clock(time(0, 5), hour12=True) == "12:05 AM"
    assert e.format_clock(time(12, 0), hour12=True) == "12:00 PM"
    assert e.format_clock(time(5, 0)) == "05:00"


# ---- window advice ---------------------------------------------------------

W = e.WindowSettings()  # pleasant 18-23, cold <= 8, hot >= 30


def test_advise_pleasant_day_with_thermostat_running_asks_to_turn_it_off():
    a = e.advise(21, 12, 15, W, thermostat_running=True, resume_text="6:00 PM")
    assert a.kind == e.ADVICE_OPEN
    assert "high of 21 degrees" in a.message and "low of 12 degrees" in a.message
    assert "open the windows" in a.message
    assert a.question == "Would you like me to turn the thermostat off until 6:00 PM?"
    assert (a.yes_action, a.no_action) == (e.ACT_OPEN, e.ACT_NONE)


def test_advise_pleasant_day_with_thermostat_already_off_asks_nothing():
    a = e.advise(21, 12, 15, W, thermostat_running=False)
    assert a.kind == e.ADVICE_OPEN and a.question is None
    assert "already off" in a.message


def test_advise_cold_day_keeps_windows_closed():
    a = e.advise(2, -5, 0, W, thermostat_running=True)
    assert a.kind == e.ADVICE_CLOSED_HEAT
    assert "cold" in a.message and "keep the heat on" in a.message
    assert a.question == "Will you be leaving the windows closed today?"
    assert (a.yes_action, a.no_action) == (e.ACT_NONE, e.ACT_OPEN)


def test_advise_cool_day_is_not_called_cold():
    a = e.advise(14, 8, 10, W, thermostat_running=True)
    assert a.kind == e.ADVICE_CLOSED_HEAT and "cool" in a.message and "cold" not in a.message


def test_advise_hot_day_suggests_ac():
    a = e.advise(31, 20, 25, W, thermostat_running=False)
    assert a.kind == e.ADVICE_CLOSED_AC and "hot" in a.message and "AC" in a.message


def test_advise_warm_day_keeps_windows_closed():
    a = e.advise(26, 17, 20, W, thermostat_running=True)
    assert a.kind == e.ADVICE_CLOSED_AC and "warm" in a.message


def test_advise_range_edges_are_pleasant():
    assert e.advise(18, None, 18, W, True).kind == e.ADVICE_OPEN
    assert e.advise(23, None, 23, W, True).kind == e.ADVICE_OPEN
    assert e.advise(17.9, None, 18, W, True).kind == e.ADVICE_CLOSED_HEAT
    assert e.advise(23.1, None, 23, W, True).kind == e.ADVICE_CLOSED_AC


def test_advise_without_forecast_uses_current_temperature_and_unit():
    a = e.advise(None, None, 20.0, W, True, unit=e.UNIT_F)
    assert a.message.startswith("It is 68 degrees outside right now.")
    assert a.kind == e.ADVICE_OPEN


def test_advise_user_example_19_to_21_still_prompts_windows():
    wide = e.WindowSettings(low=19, high=21)
    assert e.advise(19, None, 19, wide, True).kind == e.ADVICE_OPEN
    assert e.advise(21, None, 21, wide, True).kind == e.ADVICE_OPEN


def _dt(*args):
    return datetime(*args, tzinfo=UTC)


def test_next_resume_time_of_day_today_or_tomorrow():
    now = _dt(2026, 4, 10, 9, 30)
    assert e.next_resume(now, time(18, 0)) == _dt(2026, 4, 10, 18, 0)
    late = _dt(2026, 4, 10, 19, 0)
    assert e.next_resume(late, time(18, 0)) == _dt(2026, 4, 11, 18, 0)
    assert e.next_resume(_dt(2026, 4, 10, 18, 0), time(18, 0)) == _dt(2026, 4, 11, 18, 0)


def test_next_resume_cap_and_no_limit():
    now = _dt(2026, 4, 10, 9, 30)
    assert e.next_resume(now, None, 12) == _dt(2026, 4, 10, 21, 30)
    assert e.next_resume(now, time(18, 0), 4) == _dt(2026, 4, 10, 13, 30)  # cap is sooner
    assert e.next_resume(now, time(11, 0), 12) == _dt(2026, 4, 10, 11, 0)  # time is sooner
    assert e.next_resume(now, None, 0) is None


# ---- presence and away ----------------------------------------------------

HOME = (52.0, 4.0)
AWAY_TABLE = [(-20.0, 20.0), (0.0, 19.0), (20.0, 21.0), (30.0, 21.0)]


def reading(state, lat=None, lon=None, acc=None, radius=150, max_acc=200):
    return e.read_source(state, lat, lon, acc, HOME[0], HOME[1], radius, max_acc)


def test_haversine_known_distances():
    assert e.haversine_m(52, 4, 52, 4) == 0
    assert e.haversine_m(0, 0, 1, 0) == pytest.approx(111_195, rel=0.001)
    assert e.haversine_m(52, 4, 52.001, 4) == pytest.approx(111.2, rel=0.01)


def test_source_inside_and_outside_radius():
    inside = reading("home", 52.001, 4.0)  # about 111 m
    assert inside.home is True and inside.distance_m == pytest.approx(111.2, abs=1)
    assert reading("not_home", 52.002, 4.0).home is False  # about 222 m


def test_radius_decides_not_the_tracker_state():
    # The tracker says not_home, but the position is inside our own radius.
    assert reading("not_home", 52.001, 4.0, radius=300).home is True
    # The tracker says home, but the position is outside the radius.
    assert reading("home", 52.01, 4.0).home is False


def test_inaccurate_gps_is_ignored():
    assert reading("not_home", 53.0, 4.0, acc=500).home is None
    assert reading("not_home", 53.0, 4.0, acc=50).home is False


def test_state_only_sources():
    assert reading("home").home is True
    assert reading("not_home").home is False
    assert reading("Work").home is False
    assert reading("unavailable").home is None
    assert reading("unknown").home is None
    assert reading(None).home is None


def test_combine_presence():
    home, away, none = e.SourceReading(True), e.SourceReading(False), e.SourceReading(None)
    assert e.combine_presence([away, home]) == e.PRESENCE_HOME
    assert e.combine_presence([away, away]) == e.PRESENCE_AWAY
    assert e.combine_presence([away, none]) == e.PRESENCE_AWAY  # unknown phones are skipped
    assert e.combine_presence([none, none]) == e.PRESENCE_UNKNOWN
    assert e.combine_presence([]) == e.PRESENCE_UNKNOWN


def test_away_confirmed_waits_for_delay():
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert not e.away_confirmed(None, start, 10)
    assert not e.away_confirmed(start, datetime(2026, 1, 1, 12, 9, tzinfo=UTC), 10)
    assert e.away_confirmed(start, datetime(2026, 1, 1, 12, 10, tzinfo=UTC), 10)
    assert e.away_confirmed(start, start, 0)


def test_away_uses_the_away_table():
    s = make(away_setpoints=AWAY_TABLE)
    home = e.decide(0, date(2026, 1, 1), s, {"heat", "cool"})
    away = e.decide(0, date(2026, 1, 1), s, {"heat", "cool"}, away=True)
    assert home.setpoint == 22.0 and home.reason == e.R_NORMAL and not home.away
    assert away.setpoint == 19.0 and away.reason == e.R_AWAY and away.away


def test_away_without_a_table_changes_nothing():
    d = e.decide(0, date(2026, 1, 1), make(), {"heat", "cool"}, away=True)
    assert d.setpoint == 22.0 and not d.away


def test_away_wins_over_bedtime():
    s = make(
        away_setpoints=AWAY_TABLE,
        bed_setpoints=[(0.0, 18.0)],
        bed_start=time(20, 0),
        bed_end=time(5, 0),
    )
    d = e.decide(0, date(2026, 1, 1), s, {"heat", "cool"}, now=time(22, 0), away=True)
    assert d.setpoint == 19.0 and d.away and not d.bedtime


def test_mild_weather_off_still_applies_when_away():
    s = make(away_setpoints=AWAY_TABLE, off_min=15.0, off_max=22.0)
    d = e.decide(18, date(2026, 1, 1), s, {"heat", "cool"}, away=True)
    assert d.mode == e.OFF and d.reason == e.R_OFF_RANGE


def test_held_for():
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert not e.held_for(None, start, 2)
    assert not e.held_for(start, datetime(2026, 1, 1, 12, 1, tzinfo=UTC), 2)
    assert e.held_for(start, datetime(2026, 1, 1, 12, 2, tzinfo=UTC), 2)


# ---- safety temperatures --------------------------------------------------

LIMITS = e.SafetySettings(hot=30.0, cold=10.0, margin=2.0)


def test_safety_triggers_at_the_limits():
    assert e.safety_state(30.0, 20.0, LIMITS) == e.SAFETY_HOT
    assert e.safety_state(31.0, 25.0, LIMITS) == e.SAFETY_HOT
    assert e.safety_state(22.0, 10.0, LIMITS) == e.SAFETY_COLD
    assert e.safety_state(22.0, 12.0, LIMITS) is None
    assert e.safety_state(29.9, 10.1, LIMITS) is None
    assert e.safety_state(None, None, LIMITS) is None


def test_safety_holds_until_recovered_by_the_margin():
    assert e.safety_state(29.0, 25.0, LIMITS, active=e.SAFETY_HOT) == e.SAFETY_HOT
    assert e.safety_state(28.0, 25.0, LIMITS, active=e.SAFETY_HOT) is None
    assert e.safety_state(21.0, 11.0, LIMITS, active=e.SAFETY_COLD) == e.SAFETY_COLD
    assert e.safety_state(21.0, 12.0, LIMITS, active=e.SAFETY_COLD) is None
    assert e.safety_state(29.0, 25.0, LIMITS) is None  # not active: no hold


def test_safety_hot_decision_cools_to_below_the_limit():
    d = e.safety_decision(e.SAFETY_HOT, LIMITS, 5.0, {"heat", "cool"})
    assert (d.mode, d.setpoint, d.reason) == (e.COOL, 28.0, e.R_SAFETY_HOT)


def test_safety_cold_decision_heats_to_above_the_limit():
    d = e.safety_decision(e.SAFETY_COLD, LIMITS, 5.0, {"heat", "cool"})
    assert (d.mode, d.setpoint, d.reason) == (e.HEAT, 12.0, e.R_SAFETY_COLD)


def test_safety_target_respects_thermostat_limits():
    d = e.safety_decision(e.SAFETY_COLD, LIMITS, 5.0, {"heat"}, min_temp=15.0, max_temp=32.0)
    assert d.setpoint == 15.0


def test_safety_with_range_only_thermostat():
    d = e.safety_decision(e.SAFETY_HOT, LIMITS, 5.0, {"heat_cool"})
    assert (d.mode, d.low, d.high) == (e.HEAT_COOL, 26.0, 28.0)


def test_safety_without_a_usable_mode():
    assert e.safety_decision(e.SAFETY_HOT, LIMITS, 5.0, {"heat"}) is None


# ---- indoor sensors with weights and time windows -------------------------


def test_active_profile_by_time_of_day():
    night = e.IndoorProfile(time(20, 0), time(7, 0), (("sensor.crib", 1.0),))
    day = e.IndoorProfile(None, None, (("climate.hall", 1.0),))
    profiles = [night, day]
    assert e.active_indoor_profile(profiles, time(23, 0)) is night
    assert e.active_indoor_profile(profiles, time(3, 0)) is night
    assert e.active_indoor_profile(profiles, time(12, 0)) is day
    assert e.active_indoor_profile(profiles[:1], time(12, 0)) is None


def test_weighted_average_uses_weights_and_skips_missing():
    p = e.IndoorProfile(None, None, (("sensor.a", 1.0), ("sensor.b", 3.0), ("climate.hall", 0.0)))
    value, used = e.weighted_average(
        {"sensor.a": 20.0, "sensor.b": 24.0, "climate.hall": 10.0}, p
    )
    assert value == pytest.approx(23.0) and used == {"sensor.a": 1.0, "sensor.b": 3.0}
    value, used = e.weighted_average({"sensor.a": 20.0, "sensor.b": None}, p)
    assert value == 20.0 and used == {"sensor.a": 1.0}
    assert e.weighted_average({"sensor.a": None, "sensor.b": None}, p) == (None, {})


def test_compensate_shifts_all_targets_and_respects_limits():
    single = e.Decision(mode=e.HEAT, reason=e.R_NORMAL, outdoor=0, setpoint=22.0)
    assert e.compensate(single, 2.0, 9, 32).setpoint == 24.0
    assert e.compensate(single, 2.0, 9, 32).offset == 2.0
    assert e.compensate(single, 20.0, 9, 32).setpoint == 32.0
    assert e.compensate(single, -20.0, 9, 32).setpoint == 9.0
    rng = e.Decision(mode=e.HEAT_COOL, reason=e.R_NORMAL, outdoor=0, low=20.0, high=22.0)
    shifted = e.compensate(rng, -1.5, 9, 32)
    assert (shifted.low, shifted.high) == (18.5, 20.5)


def test_compensate_keeps_a_gap_in_range_mode_at_the_limit():
    rng = e.Decision(mode=e.HEAT_COOL, reason=e.R_NORMAL, outdoor=0, low=30.0, high=32.0)
    shifted = e.compensate(rng, 5.0, 9, 32)
    assert shifted.high == 32.0 and shifted.high - shifted.low >= 0.5


def test_compensate_leaves_off_and_zero_alone():
    off = e.Decision(mode=e.OFF, reason=e.R_OFF_RANGE, outdoor=18)
    assert e.compensate(off, 3.0) is off
    single = e.Decision(mode=e.HEAT, reason=e.R_NORMAL, outdoor=0, setpoint=22.0)
    assert e.compensate(single, 0.0) is single


def test_weighted_mean_defaults_to_equal_weights():
    value, used = e.weighted_mean({"a": 10.0, "b": 20.0, "c": None}, {})
    assert value == 15.0 and used == {"a": 1.0, "b": 1.0}
    assert e.weighted_mean({"a": None}, {}) == (None, {})
