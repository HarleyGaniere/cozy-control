"""Integration tests using a real Home Assistant core with mocked entities."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.cozy_control.const import (
    CONF_AWAY_ENABLED,
    CONF_AWAY_SETPOINTS,
    CONF_BED_ENABLED,
    CONF_BED_END,
    CONF_BED_SETPOINTS,
    CONF_BED_START,
    CONF_BRIEF_DATES,
    CONF_BRIEF_DATES_ENABLED,
    CONF_CLIMATE,
    CONF_CONTACT_DELAY,
    CONF_CONTACT_SOURCES,
    CONF_CONTACTS_ENABLED,
    CONF_COOL_DATES_ENABLED,
    CONF_COOL_DISABLED,
    CONF_COOL_ENABLED,
    CONF_HEAT_DATES_ENABLED,
    CONF_HEAT_DISABLED,
    CONF_HEAT_ENABLED,
    CONF_INDOOR_ENABLED,
    CONF_INDOOR_MAX_OFFSET,
    CONF_INDOOR_SOURCES,
    CONF_INDOOR_WEIGHTS,
    CONF_INDOOR_WINDOWS,
    CONF_OFF_ENABLED,
    CONF_OFF_MAX,
    CONF_OFF_MIN,
    CONF_OUTDOOR_SOURCES,
    CONF_OUTDOOR_WEIGHTS,
    CONF_PRESENCE_DELAY,
    CONF_PRESENCE_MAX_ACCURACY,
    CONF_PRESENCE_RADIUS,
    CONF_PRESENCE_SOURCES,
    CONF_SAFETY_COLD,
    CONF_SAFETY_ENABLED,
    CONF_SAFETY_HOT,
    CONF_SAFETY_SENSORS,
    CONF_SETPOINTS,
    CONF_TIME_FORMAT,
    CONF_UNIT,
    CONF_USE_FORECAST,
    CONF_WEATHER,
    CONF_WIN_MAX_HOURS,
    DOMAIN,
    default_options,
)

WEATHER = "weather.home"
SENSOR = "sensor.back_porch_temperature"
CLIMATE = "climate.hallway"


def set_weather(hass, temp, unit="°C", state="sunny"):
    hass.states.async_set(WEATHER, state, {"temperature": temp, "temperature_unit": unit})


def set_climate(hass, mode="off", unit_attrs=None, **attrs):
    base = {
        "hvac_modes": ["off", "heat", "cool", "heat_cool"],
        "min_temp": 9,
        "max_temp": 32,
        "target_temp_step": 0.5,
        "temperature": None,
        "target_temp_low": 18,
        "target_temp_high": 24,
    }
    base.update(attrs)
    hass.states.async_set(CLIMATE, mode, base)


def make_entry(hass, options=None, source=WEATHER):
    opts = default_options()
    opts.update(options or {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hallway",
        unique_id=CLIMATE,
        data={CONF_WEATHER: source, CONF_CLIMATE: CLIMATE},
        options=opts,
    )
    entry.add_to_hass(hass)
    return entry


async def setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
def calls(hass):
    return {
        "mode": async_mock_service(hass, "climate", "set_hvac_mode"),
        "temp": async_mock_service(hass, "climate", "set_temperature"),
    }


# ---------------------------------------------------------------------------


async def test_range_mode_follows_curve(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)  # curve: 21, width 2 -> 20..22
    set_climate(hass, "off")
    await setup(hass, make_entry(hass))
    assert [c.data["hvac_mode"] for c in calls["mode"]] == ["heat_cool"]
    assert calls["temp"][0].data["target_temp_low"] == 20.0
    assert calls["temp"][0].data["target_temp_high"] == 22.0
    status = hass.states.get("sensor.hallway_status")
    assert status.state == "following_curve"
    assert float(hass.states.get("sensor.hallway_target_temperature").state) == 21.0
    assert float(hass.states.get("sensor.hallway_outdoor_temperature").state) == 10.0


async def test_no_service_calls_when_already_correct(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    set_climate(hass, "heat_cool", target_temp_low=20, target_temp_high=22)
    await setup(hass, make_entry(hass))
    assert calls["mode"] == [] and calls["temp"] == []


async def test_small_drift_below_min_change_is_ignored(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    set_climate(hass, "heat_cool", target_temp_low=20.0, target_temp_high=22.0)
    entry = make_entry(hass)
    await setup(hass, entry)
    set_weather(hass, 10.4)  # curve moves 0.02 C: below the 0.5 threshold
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=61))
    await hass.async_block_till_done()
    assert calls["temp"] == []


async def test_updates_again_on_next_interval(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    set_climate(hass, "heat_cool", target_temp_low=20, target_temp_high=22)
    await setup(hass, make_entry(hass))
    set_weather(hass, -10)  # curve 22.5 -> 21.5..23.5
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=61))
    await hass.async_block_till_done()
    assert calls["temp"][-1].data["target_temp_low"] == 21.5
    assert calls["temp"][-1].data["target_temp_high"] == 23.5


async def test_custom_interval_is_used(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    set_climate(hass, "heat_cool", target_temp_low=20, target_temp_high=22)
    await setup(hass, make_entry(hass, {"update_interval": 15}))
    set_weather(hass, -10)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=16))
    await hass.async_block_till_done()
    assert calls["temp"], "15 minute interval should have refreshed after 16 minutes"


async def test_off_range_turns_thermostat_off(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 20)
    set_climate(hass, "heat_cool")
    await setup(hass, make_entry(hass, {CONF_OFF_MIN: 19.0, CONF_OFF_MAX: 21.0}))
    assert [c.data["hvac_mode"] for c in calls["mode"]] == ["off"]
    assert calls["temp"] == []
    assert hass.states.get("sensor.hallway_status").state == "outdoor_in_off_range"


async def test_heating_disabled_by_date(hass: HomeAssistant, calls, freezer) -> None:
    freezer.move_to("2026-07-15 12:00:00")
    set_weather(hass, 30)
    set_climate(hass, "off")
    await setup(hass, make_entry(hass, {CONF_HEAT_DISABLED: "06-01 to 08-31"}))
    assert [c.data["hvac_mode"] for c in calls["mode"]] == ["cool"]
    assert calls["temp"][0].data["temperature"] == 17.0
    assert hass.states.get("sensor.hallway_status").state == "heating_disabled_by_date"


async def test_cooling_disabled_by_date(hass: HomeAssistant, calls, freezer) -> None:
    freezer.move_to("2026-01-15 12:00:00")
    set_weather(hass, 0)
    set_climate(hass, "off")
    await setup(hass, make_entry(hass, {CONF_COOL_DISABLED: "11-01 to 03-01"}))
    assert [c.data["hvac_mode"] for c in calls["mode"]] == ["heat"]
    assert calls["temp"][0].data["temperature"] == 22.0


async def test_heating_and_cooling_both_switched_off(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 0)
    set_climate(hass, "heat")
    await setup(hass, make_entry(hass, {CONF_HEAT_ENABLED: False, CONF_COOL_ENABLED: False}))
    assert [c.data["hvac_mode"] for c in calls["mode"]] == ["off"]
    assert calls["temp"] == []
    assert hass.states.get("sensor.hallway_status").state == "heating_and_cooling_disabled"


async def test_thermostat_without_range_mode(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 0)
    set_climate(hass, "off", hvac_modes=["off", "heat", "cool"])
    await setup(hass, make_entry(hass))
    assert [c.data["hvac_mode"] for c in calls["mode"]] == ["heat"]
    assert calls["temp"][0].data["temperature"] == 22.0


async def test_fahrenheit_system_everything_converts(hass: HomeAssistant, calls) -> None:
    hass.config.units = US_CUSTOMARY_SYSTEM
    set_weather(hass, 50, "°F")  # 10 C -> curve 21 C -> 20..22 C
    set_climate(hass, "off", min_temp=45, max_temp=90, target_temp_step=1)
    await setup(hass, make_entry(hass))
    data = calls["temp"][0].data
    assert data["target_temp_low"] == pytest.approx(68.0, abs=0.1)  # 20 C
    # 22 C is 71.6 F, and this thermostat only moves in whole degrees F
    assert data["target_temp_high"] == pytest.approx(72.0, abs=0.1)
    # the target sensor is shown in the user's unit system automatically
    assert float(hass.states.get("sensor.hallway_target_temperature").state) == pytest.approx(
        70.0, abs=0.1
    )


async def test_temperature_sensor_as_source(hass: HomeAssistant, calls) -> None:
    hass.states.async_set(SENSOR, "0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    set_climate(hass, "off", hvac_modes=["off", "heat", "cool"])
    await setup(hass, make_entry(hass, source=SENSOR))
    assert calls["temp"][0].data["temperature"] == 22.0


async def test_source_unavailable_changes_nothing(hass: HomeAssistant, calls) -> None:
    hass.states.async_set(WEATHER, "unavailable", {})
    set_climate(hass, "off")
    await setup(hass, make_entry(hass))
    assert calls["mode"] == [] and calls["temp"] == []
    assert hass.states.get("sensor.hallway_status").state == "source_unavailable"


async def test_thermostat_unavailable_changes_nothing(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    hass.states.async_set(CLIMATE, "unavailable", {})
    await setup(hass, make_entry(hass))
    assert calls["mode"] == [] and calls["temp"] == []
    assert hass.states.get("sensor.hallway_status").state == "thermostat_unavailable"


async def test_pause_switch_stops_changes_and_persists(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    set_climate(hass, "heat_cool", target_temp_low=20, target_temp_high=22)
    entry = make_entry(hass)
    await setup(hass, entry)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.hallway_enabled"}, blocking=True
    )
    set_weather(hass, -10)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.hallway_update_now"}, blocking=True
    )
    assert calls["temp"] == []
    assert hass.states.get("sensor.hallway_status").state == "paused"
    # target sensor still shows what it WOULD do
    assert float(hass.states.get("sensor.hallway_target_temperature").state) == 22.5

    # the pause survives a reload
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.hallway_enabled").state == "off"
    assert calls["temp"] == []

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.hallway_enabled"}, blocking=True
    )
    assert calls["temp"], "resuming applies the current conditions"


async def test_thermostat_error_is_reported_not_raised(hass: HomeAssistant) -> None:
    from homeassistant.exceptions import HomeAssistantError

    async def boom(call):
        raise HomeAssistantError("eco mode is active")

    hass.services.async_register("climate", "set_hvac_mode", boom)
    hass.services.async_register("climate", "set_temperature", boom)
    set_weather(hass, 10)
    set_climate(hass, "off")
    await setup(hass, make_entry(hass))
    assert hass.states.get("sensor.hallway_status").state == "apply_failed"


# ---------------------------------------------------------------------------
# Config flow and options flow
# ---------------------------------------------------------------------------


async def test_config_flow_creates_entry(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Hallway", CONF_WEATHER: WEATHER, CONF_CLIMATE: CLIMATE, "update_interval": 30},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_WEATHER: WEATHER, CONF_CLIMATE: CLIMATE}
    assert result["options"]["update_interval"] == 30
    assert result["options"][CONF_SETPOINTS][0] == [-20.0, 23.0]
    await hass.async_block_till_done()


async def test_config_flow_rejects_second_entry_for_same_thermostat(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    make_entry(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Again", CONF_WEATHER: WEATHER, CONF_CLIMATE: CLIMATE, "update_interval": 30},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def _open_section(hass, entry, section):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": section}
    )


async def test_options_table_edit_in_celsius(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "setpoints")
    assert result["step_id"] == "setpoints"
    flow_id = result["flow_id"]
    result = await hass.config_entries.options.async_configure(
        flow_id, {CONF_SETPOINTS: "-10: 24\n15: 21\n35: 16"}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SETPOINTS] == [[-10.0, 24.0], [15.0, 21.0], [35.0, 16.0]]


async def test_options_table_shown_and_saved_in_fahrenheit(hass: HomeAssistant, calls) -> None:
    hass.config.units = US_CUSTOMARY_SYSTEM
    set_weather(hass, 50, "°F")
    set_climate(hass, "off", min_temp=45, max_temp=90, target_temp_step=1)
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "setpoints")
    flow_id = result["flow_id"]
    # the stored 20 C row is shown as 68 F
    default = next(k for k in result["data_schema"].schema if k == CONF_SETPOINTS).default()
    # -20 C -> 23 C, 0 C -> 22 C, 20 C -> 20 C, 30 C -> 17 C, shown in Fahrenheit
    assert default == "-4: 73.4\n32: 71.6\n68: 68\n86: 62.6"
    result = await hass.config_entries.options.async_configure(
        flow_id, {CONF_SETPOINTS: "32: 72\n68: 68"}
    )
    result = await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    stored = entry.options[CONF_SETPOINTS]
    assert stored[0] == pytest.approx([0.0, 22.2222], abs=0.001)
    assert stored[1] == pytest.approx([20.0, 20.0], abs=0.001)


async def test_options_unchanged_table_keeps_exact_stored_values(hass: HomeAssistant) -> None:
    hass.config.units = US_CUSTOMARY_SYSTEM
    set_weather(hass, 50, "°F")
    set_climate(hass, "off")
    entry = make_entry(hass, {CONF_SETPOINTS: [[-20.0, 23.0], [0.0, 22.0], [20.0, 20.04]]})
    await setup(hass, entry)
    result = await _open_section(hass, entry, "setpoints")
    flow_id = result["flow_id"]
    shown = next(k for k in result["data_schema"].schema if k == CONF_SETPOINTS).default()
    await hass.config_entries.options.async_configure(flow_id, {CONF_SETPOINTS: shown})
    await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert entry.options[CONF_SETPOINTS][2] == [20.0, 20.04]


async def test_options_invalid_table_shows_error(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "setpoints")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SETPOINTS: "warm: cozy"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_table"}


async def test_options_seasons_validated_and_saved(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "seasons")
    flow_id = result["flow_id"]
    bad = await hass.config_entries.options.async_configure(
        flow_id, {CONF_HEAT_DISABLED: "June to August"}
    )
    assert bad["errors"] == {"base": "invalid_dates"}
    ok = await hass.config_entries.options.async_configure(
        flow_id, {CONF_HEAT_DISABLED: "6/1 - 8/31", CONF_COOL_DISABLED: ""}
    )
    assert ok["type"] is FlowResultType.MENU
    await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert entry.options[CONF_HEAT_DISABLED] == "06-01 to 08-31"
    assert entry.options[CONF_COOL_DISABLED] == ""


async def test_options_heat_cool_switches_saved(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "heat_cool")
    assert result["type"] is FlowResultType.FORM
    flow_id = result["flow_id"]
    ok = await hass.config_entries.options.async_configure(
        flow_id, {CONF_HEAT_ENABLED: False, CONF_COOL_ENABLED: False}
    )
    assert ok["type"] is FlowResultType.MENU
    await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert entry.options[CONF_HEAT_ENABLED] is False
    assert entry.options[CONF_COOL_ENABLED] is False


async def test_options_off_range(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "off_range")
    flow_id = result["flow_id"]
    bad = await hass.config_entries.options.async_configure(flow_id, {CONF_OFF_MIN: 19})
    assert bad["errors"] == {"base": "off_range_incomplete"}
    bad = await hass.config_entries.options.async_configure(
        flow_id, {CONF_OFF_MIN: 22, CONF_OFF_MAX: 19}
    )
    assert bad["errors"] == {"base": "off_range_order"}
    await hass.config_entries.options.async_configure(flow_id, {CONF_OFF_MIN: 19, CONF_OFF_MAX: 21})
    await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert entry.options[CONF_OFF_MIN] == 19.0 and entry.options[CONF_OFF_MAX] == 21.0


async def test_options_unit_choice_changes_display_not_values(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)  # system unit is Celsius here
    await setup(hass, entry)
    result = await _open_section(hass, entry, "general")
    flow_id = result["flow_id"]
    await hass.config_entries.options.async_configure(
        flow_id,
        {
            CONF_OUTDOOR_SOURCES: [WEATHER],
            "update_interval": 60,
            CONF_UNIT: "fahrenheit",
            "min_change": 0.5,
            "range_width": 2.0,
            "interpolate": True,
        },
    )
    await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert entry.options[CONF_UNIT] == "fahrenheit"
    # the delta fields were entered in the unit shown while the form was open (Celsius)
    assert entry.options["min_change"] == 0.5
    assert entry.options[CONF_SETPOINTS][2] == [20.0, 20.0]  # real values untouched
    # reopening shows 0.5 C as 0.9 F
    again = await _open_section(hass, entry, "general")
    schema = {str(k): k for k in again["data_schema"].schema}
    assert schema["min_change"].default() == pytest.approx(0.9)


@pytest.mark.parametrize(
    ("unit_choice", "example"), [("fahrenheit", "32: 72"), ("celsius", "0: 22")]
)
async def test_options_table_example_follows_unit(
    hass: HomeAssistant, unit_choice: str, example: str
) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass, {CONF_UNIT: unit_choice})
    await setup(hass, entry)
    result = await _open_section(hass, entry, "setpoints")
    assert result["description_placeholders"]["example"] == example


async def test_bedtime_table_used_at_night(hass: HomeAssistant, calls, freezer) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-01-15 22:00:00")
    set_weather(hass, 0)
    set_climate(hass, "off", hvac_modes=["off", "heat", "cool"])
    await setup(hass, make_entry(hass, {CONF_BED_ENABLED: True}))
    assert calls["temp"][0].data["temperature"] == 18.0  # bedtime row for 0 outside
    assert hass.states.get("sensor.hallway_status").state == "following_bedtime_table"


async def test_bedtime_ignored_in_daytime_or_when_disabled(
    hass: HomeAssistant, calls, freezer
) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-01-15 12:00:00")
    set_weather(hass, 0)
    set_climate(hass, "off", hvac_modes=["off", "heat", "cool"])
    await setup(hass, make_entry(hass, {CONF_BED_ENABLED: True}))
    assert calls["temp"][0].data["temperature"] == 22.0
    assert hass.states.get("sensor.hallway_status").state == "following_curve"


async def test_bedtime_disabled_by_default(hass: HomeAssistant, calls, freezer) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-01-15 22:00:00")
    set_weather(hass, 0)
    set_climate(hass, "off", hvac_modes=["off", "heat", "cool"])
    await setup(hass, make_entry(hass))
    assert calls["temp"][0].data["temperature"] == 22.0


async def test_bedtime_start_triggers_an_update(hass: HomeAssistant, calls, freezer) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-01-15 19:59:50")
    set_weather(hass, 0)
    set_climate(hass, "off", hvac_modes=["off", "heat", "cool"])
    await setup(hass, make_entry(hass, {CONF_BED_ENABLED: True, "update_interval": 1440}))
    assert calls["temp"][0].data["temperature"] == 22.0
    set_climate(hass, "heat", hvac_modes=["off", "heat", "cool"], temperature=22.0)
    freezer.move_to("2026-01-15 20:00:01")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["temp"][-1].data["temperature"] == 18.0


async def test_options_bedtime_saved_and_validated(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "bedtime")
    assert result["type"] is FlowResultType.FORM
    flow_id = result["flow_id"]
    base = {
        CONF_BED_ENABLED: True,
        CONF_BED_START: "21:30:00",
        CONF_BED_END: "06:00:00",
        CONF_BED_SETPOINTS: "0: 18\n20: 17",
    }
    same = await hass.config_entries.options.async_configure(
        flow_id, {**base, CONF_BED_END: "21:30:00"}
    )
    assert same["errors"] == {"base": "bedtime_same_time"}
    bad = await hass.config_entries.options.async_configure(
        flow_id, {**base, CONF_BED_SETPOINTS: "cold: cozy"}
    )
    assert bad["errors"] == {"base": "invalid_table"}
    ok = await hass.config_entries.options.async_configure(flow_id, base)
    assert ok["type"] is FlowResultType.MENU
    await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert entry.options[CONF_BED_ENABLED] is True
    assert entry.options[CONF_BED_START] == "21:30"
    assert entry.options[CONF_BED_END] == "06:00"
    assert entry.options[CONF_BED_SETPOINTS] == [[0.0, 18.0], [20.0, 17.0]]


async def test_options_bedtime_table_shown_in_fahrenheit(hass: HomeAssistant) -> None:
    set_weather(hass, 50, "°F")
    set_climate(hass, "off")
    entry = make_entry(hass, {CONF_UNIT: "fahrenheit"})
    await setup(hass, entry)
    result = await _open_section(hass, entry, "bedtime")
    shown = next(k for k in result["data_schema"].schema if k == CONF_BED_SETPOINTS).default()
    assert shown.splitlines()[2] == "68: 62.6"  # 20 C outside -> 17 C inside


async def test_options_bedtime_twelve_hour_display_and_input(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass, {CONF_TIME_FORMAT: "12h"})
    await setup(hass, entry)
    result = await _open_section(hass, entry, "bedtime")
    flow_id = result["flow_id"]
    schema = {str(k): k for k in result["data_schema"].schema}
    assert schema[CONF_BED_START].default() == "8:00 PM"
    assert schema[CONF_BED_END].default() == "5:00 AM"
    assert "8:00 PM" in result["description_placeholders"]["time_example"]
    bad = await hass.config_entries.options.async_configure(
        flow_id,
        {
            CONF_BED_ENABLED: True,
            CONF_BED_START: "late",
            CONF_BED_END: "5 am",
            CONF_BED_SETPOINTS: schema[CONF_BED_SETPOINTS].default(),
        },
    )
    assert bad["errors"] == {"base": "invalid_time"}
    await hass.config_entries.options.async_configure(
        flow_id,
        {
            CONF_BED_ENABLED: True,
            CONF_BED_START: "9:30 pm",
            CONF_BED_END: "6 am",
            CONF_BED_SETPOINTS: schema[CONF_BED_SETPOINTS].default(),
        },
    )
    await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert entry.options[CONF_BED_START] == "21:30"  # always stored as 24 hour
    assert entry.options[CONF_BED_END] == "06:00"


async def test_options_time_format_toggle_changes_bedtime_display(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "general")
    flow_id = result["flow_id"]
    fields = {str(k): k for k in result["data_schema"].schema}
    assert fields[CONF_TIME_FORMAT].default() == "24h"
    values = {name: key.default() for name, key in fields.items()}
    values[CONF_TIME_FORMAT] = "12h"
    menu = await hass.config_entries.options.async_configure(flow_id, values)
    assert menu["type"] is FlowResultType.MENU
    bedtime = await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "bedtime"}
    )
    shown = {str(k): k for k in bedtime["data_schema"].schema}
    assert shown[CONF_BED_START].default() == "8:00 PM"
    assert shown[CONF_BED_END].default() == "5:00 AM"


async def test_options_bedtime_table_defaults_for_older_entries(hass: HomeAssistant) -> None:
    """Entries created before bedtime existed have no bedtime table stored."""
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    options = dict(entry.options)
    for key in (CONF_BED_ENABLED, CONF_BED_START, CONF_BED_END, CONF_BED_SETPOINTS):
        options.pop(key, None)
    hass.config_entries.async_update_entry(entry, options=options)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "bedtime")
    shown = {str(k): k for k in result["data_schema"].schema}
    assert shown[CONF_BED_SETPOINTS].default() == "-20: 19\n0: 18\n20: 17\n30: 17"
    assert shown[CONF_BED_START].default() == "20:00"


def test_translations_do_not_quote_placeholders() -> None:
    """Home Assistant treats 'single quotes' around {braces} as literal text."""
    import json
    import pathlib
    import re

    path = pathlib.Path("custom_components/cozy_control/translations/en.json")
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"'\{|\}'", text)
    json.loads(text)


async def test_off_range_switched_off_is_ignored(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 20)
    set_climate(hass, "off", hvac_modes=["off", "heat", "cool"])
    options = {CONF_OFF_MIN: 19.0, CONF_OFF_MAX: 21.0, CONF_OFF_ENABLED: False}
    await setup(hass, make_entry(hass, options))
    assert hass.states.get("sensor.hallway_status").state == "following_curve"


async def test_off_range_legacy_entry_without_switch_still_works(
    hass: HomeAssistant, calls
) -> None:
    set_weather(hass, 20)
    set_climate(hass, "heat_cool")
    entry = make_entry(hass, {CONF_OFF_MIN: 19.0, CONF_OFF_MAX: 21.0})
    assert CONF_OFF_ENABLED not in entry.options
    await setup(hass, entry)
    assert hass.states.get("sensor.hallway_status").state == "outdoor_in_off_range"


async def test_options_off_range_toggle_keeps_values(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass, {CONF_OFF_MIN: 19.0, CONF_OFF_MAX: 21.0})
    await setup(hass, entry)
    result = await _open_section(hass, entry, "off_range")
    flow_id = result["flow_id"]
    fields = {str(k): k for k in result["data_schema"].schema}
    assert fields[CONF_OFF_ENABLED].default() is True  # filled-in legacy range counts as on
    await hass.config_entries.options.async_configure(
        flow_id, {CONF_OFF_ENABLED: False, CONF_OFF_MIN: 19, CONF_OFF_MAX: 21}
    )
    await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert entry.options[CONF_OFF_ENABLED] is False
    assert entry.options[CONF_OFF_MIN] == 19.0 and entry.options[CONF_OFF_MAX] == 21.0


async def test_options_off_range_on_needs_values(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "off_range")
    flow_id = result["flow_id"]
    bad = await hass.config_entries.options.async_configure(flow_id, {CONF_OFF_ENABLED: True})
    assert bad["errors"] == {"base": "off_range_needed"}
    ok = await hass.config_entries.options.async_configure(flow_id, {CONF_OFF_ENABLED: False})
    assert ok["type"] is FlowResultType.MENU


async def test_heat_dates_switched_off_are_ignored(hass: HomeAssistant, calls, freezer) -> None:
    freezer.move_to("2026-07-15 12:00:00")
    set_weather(hass, 30)
    set_climate(hass, "off")
    options = {CONF_HEAT_DISABLED: "06-01 to 08-31", CONF_HEAT_DATES_ENABLED: False}
    await setup(hass, make_entry(hass, options))
    assert hass.states.get("sensor.hallway_status").state == "following_curve"
    assert [c.data["hvac_mode"] for c in calls["mode"]] == ["heat_cool"]


async def test_options_season_toggles_keep_dates(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass, {CONF_HEAT_DISABLED: "05-01 to 09-01", CONF_COOL_DISABLED: "11-01 to 03-01"})
    await setup(hass, entry)
    assert CONF_HEAT_DATES_ENABLED not in entry.options  # older entry: counts as on
    result = await _open_section(hass, entry, "seasons")
    flow_id = result["flow_id"]
    fields = {str(k): k for k in result["data_schema"].schema}
    assert fields[CONF_HEAT_DATES_ENABLED].default() is True
    assert fields[CONF_COOL_DATES_ENABLED].default() is True
    await hass.config_entries.options.async_configure(
        flow_id,
        {
            CONF_HEAT_DATES_ENABLED: False,
            CONF_HEAT_DISABLED: "05-01 to 09-01",
            CONF_COOL_DATES_ENABLED: True,
            CONF_COOL_DISABLED: "11-01 to 03-01",
        },
    )
    await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert entry.options[CONF_HEAT_DATES_ENABLED] is False
    assert entry.options[CONF_COOL_DATES_ENABLED] is True
    assert entry.options[CONF_HEAT_DISABLED] == "05-01 to 09-01"  # remembered while off


# ---- windows, briefing and answers ------------------------------------------

WINDOWS = "switch.hallway_windows_open"


def mock_forecast(hass, high, low, unit_note=None):
    items = [{"datetime": dt_util.now().isoformat(), "temperature": high, "templow": low}]
    return async_mock_service(
        hass,
        "weather",
        "get_forecasts",
        response={WEATHER: {"forecast": items}},
        supports_response=SupportsResponse.ONLY,
    )


async def call(hass, service, data=None, response=False):
    return await hass.services.async_call(
        DOMAIN,
        service,
        {"entity_id": WINDOWS, **(data or {})},
        blocking=True,
        return_response=response,
    )


async def briefing(hass, data=None):
    result = await call(hass, "morning_briefing", data, response=True)
    return result[WINDOWS]


async def test_windows_switch_turns_thermostat_off_and_back(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    set_climate(hass, "heat_cool", target_temp_low=20, target_temp_high=22)
    await setup(hass, make_entry(hass))
    assert hass.states.get(WINDOWS).state == "off"
    assert calls["mode"] == []

    await hass.services.async_call("switch", "turn_on", {"entity_id": WINDOWS}, blocking=True)
    assert hass.states.get(WINDOWS).state == "on"
    assert [c.data["hvac_mode"] for c in calls["mode"]] == ["off"]
    assert hass.states.get("sensor.hallway_status").state == "windows_open"

    set_climate(hass, "off")
    await hass.services.async_call("switch", "turn_off", {"entity_id": WINDOWS}, blocking=True)
    assert hass.states.get(WINDOWS).state == "off"
    assert calls["mode"][-1].data["hvac_mode"] == "heat_cool"
    assert hass.states.get("sensor.hallway_status").state == "following_curve"


async def test_windows_open_stays_off_through_updates(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    set_climate(hass, "heat_cool")
    await setup(hass, make_entry(hass))
    await call(hass, "windows_opened")
    set_climate(hass, "off")
    set_weather(hass, -15)  # a big weather change must not wake the thermostat
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=61))
    await hass.async_block_till_done()
    assert [c.data["hvac_mode"] for c in calls["mode"]] == ["off"]
    assert hass.states.get("sensor.hallway_status").state == "windows_open"


async def test_windows_open_works_without_outdoor_reading(hass: HomeAssistant, calls) -> None:
    hass.states.async_set(WEATHER, "unavailable")
    set_climate(hass, "heat_cool")
    await setup(hass, make_entry(hass))
    assert hass.states.get("sensor.hallway_status").state == "source_unavailable"
    await call(hass, "windows_opened")
    assert [c.data["hvac_mode"] for c in calls["mode"]] == ["off"]


async def test_windows_opened_with_hours_resumes_by_itself(
    hass: HomeAssistant, calls, freezer
) -> None:
    freezer.move_to("2026-04-10 09:00:00")
    set_weather(hass, 10)
    set_climate(hass, "heat_cool")
    await setup(hass, make_entry(hass))
    await call(hass, "windows_opened", {"hours": 2})
    assert hass.states.get(WINDOWS).state == "on"
    set_climate(hass, "off")
    freezer.move_to("2026-04-10 11:01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(WINDOWS).state == "off"
    assert calls["mode"][-1].data["hvac_mode"] == "heat_cool"


async def test_windows_open_safety_cap_default_is_twelve_hours(
    hass: HomeAssistant, calls, freezer
) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-04-10 09:00:00")
    set_weather(hass, 10)
    set_climate(hass, "heat_cool")
    await setup(hass, make_entry(hass))
    await hass.services.async_call("switch", "turn_on", {"entity_id": WINDOWS}, blocking=True)
    assert hass.states.get(WINDOWS).attributes["resumes_at"].startswith("2026-04-10T21:00:00")
    set_climate(hass, "off")
    freezer.move_to("2026-04-10 21:00:30")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(WINDOWS).state == "off"


async def test_windows_open_without_cap_stays_open(hass: HomeAssistant, calls, freezer) -> None:
    freezer.move_to("2026-04-10 09:00:00")
    set_weather(hass, 10)
    set_climate(hass, "heat_cool")
    await setup(hass, make_entry(hass, {CONF_WIN_MAX_HOURS: 0}))
    await hass.services.async_call("switch", "turn_on", {"entity_id": WINDOWS}, blocking=True)
    assert hass.states.get(WINDOWS).attributes["resumes_at"] is None
    freezer.move_to("2026-04-12 09:00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(WINDOWS).state == "on"


async def test_windows_state_survives_reload(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    set_climate(hass, "heat_cool")
    entry = make_entry(hass, {CONF_WIN_MAX_HOURS: 0})
    await setup(hass, entry)
    await call(hass, "windows_opened")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(WINDOWS).state == "on"
    assert hass.states.get("sensor.hallway_status").state == "windows_open"


async def test_windows_closed_service(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    set_climate(hass, "heat_cool")
    await setup(hass, make_entry(hass))
    await call(hass, "windows_opened")
    await call(hass, "windows_closed")
    assert hass.states.get(WINDOWS).state == "off"


async def test_briefing_pleasant_day_asks_and_yes_turns_thermostat_off(
    hass: HomeAssistant, calls, freezer
) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-04-10 07:00:00")
    set_weather(hass, 12)
    set_climate(hass, "heat_cool")
    mock_forecast(hass, 21, 11)
    await setup(hass, make_entry(hass))
    result = await briefing(hass)
    assert result["active"] is True and result["advice"] == "open_windows"
    assert "high of 21 degrees" in result["message"]
    assert result["question"] == "Would you like me to turn the thermostat off until 18:00?"
    answer = await call(hass, "answer", {"answer": "yes"}, response=True)
    assert answer[WINDOWS]["handled"] is True
    assert answer[WINDOWS]["message"] == "Okay, the thermostat is off until 18:00."
    assert hass.states.get(WINDOWS).state == "on"
    assert hass.states.get(WINDOWS).attributes["resumes_at"].startswith("2026-04-10T18:00:00")
    assert calls["mode"][-1].data["hvac_mode"] == "off"


async def test_briefing_pleasant_day_no_keeps_thermostat_running(
    hass: HomeAssistant, calls
) -> None:
    set_weather(hass, 12)
    set_climate(hass, "heat_cool")
    mock_forecast(hass, 21, 11)
    await setup(hass, make_entry(hass))
    await briefing(hass)
    answer = await call(hass, "answer", {"answer": "no"}, response=True)
    assert answer[WINDOWS]["message"] == "Okay, I will keep the thermostat running."
    assert hass.states.get(WINDOWS).state == "off"
    assert [c for c in calls["mode"] if c.data["hvac_mode"] == "off"] == []


async def test_briefing_cold_day_advises_closed_windows(hass: HomeAssistant, calls) -> None:
    set_weather(hass, -2)
    set_climate(hass, "heat_cool")
    mock_forecast(hass, 3, -6)
    await setup(hass, make_entry(hass))
    result = await briefing(hass)
    assert result["advice"] == "keep_closed_heat"
    assert "keep the heat on" in result["message"]
    assert result["question"] == "Will you be leaving the windows closed today?"
    # "No" means the windows will be opened anyway
    answer = await call(hass, "answer", {"answer": "no"}, response=True)
    assert answer[WINDOWS]["handled"] is True
    assert hass.states.get(WINDOWS).state == "on"


async def test_briefing_cold_day_yes_changes_nothing(hass: HomeAssistant, calls) -> None:
    set_weather(hass, -2)
    set_climate(hass, "heat_cool")
    mock_forecast(hass, 3, -6)
    await setup(hass, make_entry(hass))
    await briefing(hass)
    await call(hass, "answer", {"answer": "yes"}, response=True)
    assert hass.states.get(WINDOWS).state == "off"


async def test_briefing_hot_day_advises_ac(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 27)
    set_climate(hass, "heat_cool")
    mock_forecast(hass, 31, 21)
    await setup(hass, make_entry(hass))
    result = await briefing(hass)
    assert result["advice"] == "keep_closed_ac" and "AC" in result["message"]


async def test_briefing_without_forecast_uses_current_temperature(
    hass: HomeAssistant, calls
) -> None:
    set_weather(hass, 20)
    set_climate(hass, "heat_cool")
    await setup(hass, make_entry(hass, {CONF_USE_FORECAST: False}))
    result = await briefing(hass)
    assert result["message"].startswith("It is 20 degrees outside right now.")


async def test_briefing_with_temperature_sensor_source(hass: HomeAssistant, calls) -> None:
    hass.states.async_set(SENSOR, "20", {"unit_of_measurement": "°C", "device_class": "temperature"})
    set_climate(hass, "heat_cool")
    await setup(hass, make_entry(hass, source=SENSOR))
    result = await briefing(hass)
    assert result["advice"] == "open_windows"
    assert result["message"].startswith("It is 20 degrees outside right now.")


async def test_briefing_pleasant_day_with_thermostat_off_asks_nothing(
    hass: HomeAssistant, calls
) -> None:
    set_weather(hass, 20)
    set_climate(hass, "off")
    mock_forecast(hass, 21, 15)
    await setup(hass, make_entry(hass, {CONF_OFF_MIN: 17.0, CONF_OFF_MAX: 23.0}))
    result = await briefing(hass)
    assert result["advice"] == "open_windows" and result["question"] is None
    answer = await call(hass, "answer", {"answer": "yes"}, response=True)
    assert answer[WINDOWS]["handled"] is False


async def test_briefing_speaks_on_notify_entity(hass: HomeAssistant, calls) -> None:
    sent = async_mock_service(hass, "notify", "send_message")
    set_weather(hass, 12)
    set_climate(hass, "heat_cool")
    mock_forecast(hass, 21, 11)
    await setup(hass, make_entry(hass))
    await briefing(hass, {"notify_entity": "notify.kitchen_echo_announce"})
    assert len(sent) == 1
    assert sent[0].data["entity_id"] == "notify.kitchen_echo_announce"
    assert "good day to open the windows" in sent[0].data["message"]
    assert "Would you like me to turn the thermostat off" in sent[0].data["message"]


async def test_briefing_ends_a_windows_open_period(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 12)
    set_climate(hass, "heat_cool")
    mock_forecast(hass, 21, 11)
    await setup(hass, make_entry(hass, {CONF_WIN_MAX_HOURS: 0}))
    await call(hass, "windows_opened")
    assert hass.states.get(WINDOWS).state == "on"
    await briefing(hass)
    assert hass.states.get(WINDOWS).state == "off"


async def test_briefing_only_inside_chosen_dates(hass: HomeAssistant, calls, freezer) -> None:
    set_weather(hass, 12)
    set_climate(hass, "heat_cool")
    mock_forecast(hass, 21, 11)
    options = {CONF_BRIEF_DATES_ENABLED: True, CONF_BRIEF_DATES: "03-15 to 05-31\n09-15 to 11-15"}
    await setup(hass, make_entry(hass, options))
    freezer.move_to("2026-07-15 07:00:00")
    summer = await briefing(hass)
    assert summer == {"active": False, "advice": None, "message": "", "question": None}
    freezer.move_to("2026-04-15 07:00:00")
    spring = await briefing(hass)
    assert spring["active"] is True and spring["advice"] == "open_windows"
    freezer.move_to("2026-10-01 07:00:00")
    assert (await briefing(hass))["active"] is True


async def test_briefing_dates_on_but_empty_means_all_year(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 12)
    set_climate(hass, "heat_cool")
    mock_forecast(hass, 21, 11)
    await setup(hass, make_entry(hass, {CONF_BRIEF_DATES_ENABLED: True, CONF_BRIEF_DATES: ""}))
    assert (await briefing(hass))["active"] is True


async def test_answer_without_question_or_after_it_expires(
    hass: HomeAssistant, calls, freezer
) -> None:
    freezer.move_to("2026-04-10 07:00:00")
    set_weather(hass, 12)
    set_climate(hass, "heat_cool")
    mock_forecast(hass, 21, 11)
    await setup(hass, make_entry(hass))
    none = await call(hass, "answer", {"answer": "yes"}, response=True)
    assert none[WINDOWS] == {
        "handled": False,
        "message": "There is no question waiting for an answer.",
    }
    await briefing(hass)
    freezer.move_to("2026-04-10 09:30:00")  # two and a half hours later
    late = await call(hass, "answer", {"answer": "yes"}, response=True)
    assert late[WINDOWS]["handled"] is False
    assert hass.states.get(WINDOWS).state == "off"


async def test_briefing_in_fahrenheit_speaks_fahrenheit(hass: HomeAssistant, calls) -> None:
    hass.config.units = US_CUSTOMARY_SYSTEM
    set_weather(hass, 54, "°F")
    set_climate(hass, "heat_cool", min_temp=45, max_temp=90, target_temp_step=1)
    items = [{"datetime": dt_util.now().isoformat(), "temperature": 70, "templow": 52}]
    async_mock_service(
        hass,
        "weather",
        "get_forecasts",
        response={WEATHER: {"forecast": items}},
        supports_response=SupportsResponse.ONLY,
    )
    await setup(hass, make_entry(hass))
    result = await briefing(hass)
    assert "high of 70 degrees" in result["message"] and "low of 52 degrees" in result["message"]
    assert result["advice"] == "open_windows"  # 70 F is 21 C


async def test_windows_opened_until_a_time_of_day(hass: HomeAssistant, calls, freezer) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-04-10 09:00:00")
    set_weather(hass, 10)
    set_climate(hass, "heat_cool")
    await setup(hass, make_entry(hass))
    await call(hass, "windows_opened", {"until": "15:30:00"})
    assert hass.states.get(WINDOWS).attributes["resumes_at"].startswith("2026-04-10T15:30:00")


async def test_options_windows_page_saved_and_validated(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "windows")
    flow_id = result["flow_id"]
    fields = {str(k): k for k in result["data_schema"].schema}
    assert fields["win_low"].default() == 18.0 and fields["hot_at"].default() == 30.0
    base = {
        CONF_USE_FORECAST: True,
        "cold_at": 6,
        "win_low": 19,
        "win_high": 21,
        "hot_at": 28,
        "win_resume": "7 pm",
        CONF_WIN_MAX_HOURS: 10,
        CONF_BRIEF_DATES_ENABLED: True,
        CONF_BRIEF_DATES: "3/15 - 5/31",
    }
    bad_order = await hass.config_entries.options.async_configure(
        flow_id, {**base, "win_low": 22, "win_high": 20}
    )
    assert bad_order["errors"] == {"base": "window_order"}
    bad_time = await hass.config_entries.options.async_configure(
        flow_id, {**base, "win_resume": "teatime"}
    )
    assert bad_time["errors"] == {"base": "invalid_windows_input"}
    ok = await hass.config_entries.options.async_configure(flow_id, base)
    assert ok["type"] is FlowResultType.MENU
    await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert entry.options["win_low"] == 19.0 and entry.options["win_high"] == 21.0
    assert entry.options["cold_at"] == 6.0 and entry.options["hot_at"] == 28.0
    assert entry.options["win_resume"] == "19:00"
    assert entry.options[CONF_WIN_MAX_HOURS] == 10.0
    assert entry.options[CONF_BRIEF_DATES] == "03-15 to 05-31"


def test_translations_have_no_literal_backslash_n() -> None:
    import json
    import pathlib

    path = pathlib.Path("custom_components/cozy_control/translations/en.json")
    strings = list(_walk_strings(json.loads(path.read_text(encoding="utf-8"))))
    assert strings
    assert not [value for value in strings if "\\n" in value]


def _walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _walk_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_strings(value)


# ---------------------------------------------------------------------------
# Presence and Away mode
# ---------------------------------------------------------------------------


ALICE = "device_tracker.alice_phone"
BOB = "person.bob"
MODES = ["off", "heat", "cool"]


def phone(hass, entity_id, where, accuracy=10, name=None):
    """Put a phone at home, nearby (inside the radius) or far away."""
    lat, lon = hass.config.latitude, hass.config.longitude
    attrs = {"friendly_name": name or entity_id.split(".")[1].split("_")[0].title()}
    if where == "home":
        hass.states.async_set(entity_id, "home", {**attrs, "latitude": lat, "longitude": lon,
                                                  "gps_accuracy": accuracy})
    elif where == "far":
        hass.states.async_set(entity_id, "not_home", {**attrs, "latitude": lat + 0.1,
                                                      "longitude": lon, "gps_accuracy": accuracy})
    else:
        hass.states.async_set(entity_id, where, attrs)


def away_options(**extra):
    return {
        CONF_AWAY_ENABLED: True,
        CONF_PRESENCE_SOURCES: [ALICE, BOB],
        CONF_PRESENCE_DELAY: 10,
        **extra,
    }


async def _away_setup(hass, freezer, options=None):
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-01-15 12:00:00")
    set_weather(hass, 0)  # home: 22, away: 19
    set_climate(hass, "off", hvac_modes=MODES)
    await setup(hass, make_entry(hass, options or away_options()))


async def test_away_after_everyone_has_been_gone_for_the_delay(
    hass: HomeAssistant, calls, freezer
) -> None:
    phone(hass, ALICE, "far")
    phone(hass, BOB, "far")
    await _away_setup(hass, freezer)
    assert calls["temp"][-1].data["temperature"] == 22.0  # delay not over yet
    assert hass.states.get("sensor.hallway_presence").state == "home"
    freezer.move_to("2026-01-15 12:11:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["temp"][-1].data["temperature"] == 19.0
    assert hass.states.get("sensor.hallway_status").state == "following_away_table"
    assert hass.states.get("sensor.hallway_presence").state == "away"


async def test_one_person_home_keeps_the_normal_table(
    hass: HomeAssistant, calls, freezer
) -> None:
    phone(hass, ALICE, "far")
    phone(hass, BOB, "home")
    await _away_setup(hass, freezer)
    freezer.move_to("2026-01-15 13:00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["temp"][-1].data["temperature"] == 22.0
    assert hass.states.get("sensor.hallway_status").state == "following_curve"


async def test_coming_home_takes_effect_immediately(
    hass: HomeAssistant, calls, freezer
) -> None:
    phone(hass, ALICE, "far")
    phone(hass, BOB, "far")
    await _away_setup(hass, freezer)
    freezer.move_to("2026-01-15 12:11:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["temp"][-1].data["temperature"] == 19.0
    set_climate(hass, "heat", hvac_modes=MODES, temperature=19.0)
    phone(hass, BOB, "home")
    await hass.async_block_till_done()
    assert calls["temp"][-1].data["temperature"] == 22.0
    assert hass.states.get("sensor.hallway_presence").state == "home"


async def test_a_short_trip_never_triggers_away(hass: HomeAssistant, calls, freezer) -> None:
    phone(hass, ALICE, "home")
    phone(hass, BOB, "home")
    await _away_setup(hass, freezer)
    phone(hass, ALICE, "far")
    phone(hass, BOB, "far")
    await hass.async_block_till_done()
    freezer.move_to("2026-01-15 12:05:00")  # back before the 10 minute delay
    phone(hass, ALICE, "home")
    await hass.async_block_till_done()
    freezer.move_to("2026-01-15 12:30:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert {c.data["temperature"] for c in calls["temp"]} == {22.0}


async def test_a_source_can_be_switched_off(hass: HomeAssistant, calls, freezer) -> None:
    phone(hass, ALICE, "far")
    phone(hass, BOB, "home")  # Bob is home, but his phone is not tracked
    await _away_setup(hass, freezer)
    assert hass.states.get("switch.hallway_track_bob").state == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.hallway_track_bob"}, blocking=True
    )
    freezer.move_to("2026-01-15 12:11:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["temp"][-1].data["temperature"] == 19.0  # only Alice counts now
    assert hass.states.get("switch.hallway_track_bob").state == "off"
    sources = hass.states.get("sensor.hallway_presence").attributes["sources"]
    assert sources[BOB]["enabled"] is False and sources[ALICE]["home"] is False


async def test_switched_off_sources_are_remembered(hass: HomeAssistant, calls, freezer) -> None:
    phone(hass, ALICE, "home")
    phone(hass, BOB, "home")
    await _away_setup(hass, freezer)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.hallway_track_alice"}, blocking=True
    )
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.hallway_track_alice").state == "off"
    assert hass.states.get("switch.hallway_track_bob").state == "on"


async def test_unreadable_phones_never_cause_away(hass: HomeAssistant, calls, freezer) -> None:
    phone(hass, ALICE, "unavailable")
    phone(hass, BOB, "unknown")
    await _away_setup(hass, freezer)
    freezer.move_to("2026-01-15 14:00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["temp"][-1].data["temperature"] == 22.0
    assert hass.states.get("sensor.hallway_presence").state == "unknown"


async def test_inaccurate_gps_does_not_cause_away(hass: HomeAssistant, calls, freezer) -> None:
    phone(hass, ALICE, "far", accuracy=900)  # a wild fix, ignored
    phone(hass, BOB, "far", accuracy=900)
    await _away_setup(hass, freezer)
    freezer.move_to("2026-01-15 14:00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["temp"][-1].data["temperature"] == 22.0


async def test_radius_is_respected(hass: HomeAssistant, calls, freezer) -> None:
    # About 11 km away, but the radius is 20 km: still home.
    phone(hass, ALICE, "far")
    phone(hass, BOB, "far")
    await _away_setup(hass, freezer, away_options(**{CONF_PRESENCE_RADIUS: 20000}))
    freezer.move_to("2026-01-15 14:00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["temp"][-1].data["temperature"] == 22.0
    assert hass.states.get("sensor.hallway_presence").state == "home"


async def test_away_mode_off_ignores_phones(hass: HomeAssistant, calls, freezer) -> None:
    phone(hass, ALICE, "far")
    phone(hass, BOB, "far")
    await _away_setup(hass, freezer, away_options(**{CONF_AWAY_ENABLED: False}))
    freezer.move_to("2026-01-15 14:00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["temp"][-1].data["temperature"] == 22.0
    assert hass.states.get("sensor.hallway_presence") is None
    assert hass.states.get("switch.hallway_track_alice") is None


async def test_options_presence_and_away_table_saved(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "presence")
    assert result["type"] is FlowResultType.FORM
    flow_id = result["flow_id"]
    ok = await hass.config_entries.options.async_configure(
        flow_id,
        {
            CONF_AWAY_ENABLED: True,
            CONF_PRESENCE_SOURCES: [ALICE, BOB],
            CONF_PRESENCE_RADIUS: 250,
            CONF_PRESENCE_DELAY: 15,
            CONF_PRESENCE_MAX_ACCURACY: 100,
        },
    )
    assert ok["type"] is FlowResultType.MENU
    table = await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "away_temps"}
    )
    assert table["type"] is FlowResultType.FORM
    bad = await hass.config_entries.options.async_configure(
        flow_id, {CONF_AWAY_SETPOINTS: "cold: cozy"}
    )
    assert bad["errors"] == {"base": "invalid_table"}
    await hass.config_entries.options.async_configure(
        flow_id, {CONF_AWAY_SETPOINTS: "0: 17\n20: 19"}
    )
    await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert entry.options[CONF_AWAY_ENABLED] is True
    assert entry.options[CONF_PRESENCE_SOURCES] == [ALICE, BOB]
    assert entry.options[CONF_PRESENCE_RADIUS] == 250
    assert entry.options[CONF_PRESENCE_DELAY] == 15
    assert entry.options[CONF_PRESENCE_MAX_ACCURACY] == 100
    assert entry.options[CONF_AWAY_SETPOINTS] == [[0.0, 17.0], [20.0, 19.0]]


# ---------------------------------------------------------------------------
# Window and door sensors
# ---------------------------------------------------------------------------


WIN1 = "binary_sensor.kitchen_window"
WIN2 = "binary_sensor.bedroom_window"
PATIO = "binary_sensor.patio_door"


def contact(hass, entity_id, state, name=None):
    hass.states.async_set(
        entity_id,
        state,
        {"friendly_name": name or entity_id.split(".")[1].replace("_", " ").title()},
    )


def contact_options(**extra):
    return {
        CONF_CONTACTS_ENABLED: True,
        CONF_CONTACT_SOURCES: [WIN1, WIN2, PATIO],
        CONF_CONTACT_DELAY: 2,
        **extra,
    }


async def _contact_setup(hass, freezer, options=None):
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-01-15 12:00:00")
    set_weather(hass, 0)
    set_climate(hass, "heat", hvac_modes=MODES, temperature=22.0)
    await setup(hass, make_entry(hass, options or contact_options()))


async def test_open_window_turns_thermostat_off_after_delay(
    hass: HomeAssistant, calls, freezer
) -> None:
    for w in (WIN1, WIN2, PATIO):
        contact(hass, w, "off")
    await _contact_setup(hass, freezer)
    assert calls["mode"] == []
    contact(hass, WIN2, "on")
    await hass.async_block_till_done()
    assert calls["mode"] == []  # not yet: the delay is 2 minutes
    freezer.move_to("2026-01-15 12:03:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [c.data["hvac_mode"] for c in calls["mode"]] == ["off"]
    assert hass.states.get("sensor.hallway_status").state == "door_or_window_open"
    sensor = hass.states.get("sensor.hallway_open_windows_and_doors")
    assert sensor.state == "1"
    assert sensor.attributes["open"] == ["Bedroom Window"]
    assert sensor.attributes["thermostat_held_off"] is True


async def test_closing_the_last_opening_resumes(
    hass: HomeAssistant, calls, freezer
) -> None:
    for w in (WIN1, WIN2, PATIO):
        contact(hass, w, "off")
    await _contact_setup(hass, freezer)
    contact(hass, WIN1, "on")
    contact(hass, PATIO, "on")
    await hass.async_block_till_done()
    freezer.move_to("2026-01-15 12:03:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["mode"][-1].data["hvac_mode"] == "off"
    set_climate(hass, "off", hvac_modes=MODES)
    contact(hass, WIN1, "off")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.hallway_status").state == "door_or_window_open"  # patio still open
    contact(hass, PATIO, "off")
    await hass.async_block_till_done()
    # Quick successive changes are batched by Home Assistant for a few seconds.
    freezer.move_to("2026-01-15 12:03:20")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["mode"][-1].data["hvac_mode"] == "heat"
    assert hass.states.get("sensor.hallway_status").state == "following_curve"


async def test_briefly_open_door_does_not_switch_heating_off(
    hass: HomeAssistant, calls, freezer
) -> None:
    for w in (WIN1, WIN2, PATIO):
        contact(hass, w, "off")
    await _contact_setup(hass, freezer)
    contact(hass, PATIO, "on")
    await hass.async_block_till_done()
    freezer.move_to("2026-01-15 12:01:00")
    contact(hass, PATIO, "off")
    await hass.async_block_till_done()
    freezer.move_to("2026-01-15 12:30:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["mode"] == []


async def test_unavailable_sensors_are_ignored(hass: HomeAssistant, calls, freezer) -> None:
    contact(hass, WIN1, "unavailable")
    contact(hass, WIN2, "unknown")
    contact(hass, PATIO, "off")
    await _contact_setup(hass, freezer)
    freezer.move_to("2026-01-15 13:00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["mode"] == []
    assert hass.states.get("sensor.hallway_open_windows_and_doors").state == "0"


async def test_window_sensors_off_by_default_or_when_disabled(
    hass: HomeAssistant, calls, freezer
) -> None:
    for w in (WIN1, WIN2, PATIO):
        contact(hass, w, "on")
    await _contact_setup(hass, freezer, contact_options(**{CONF_CONTACTS_ENABLED: False}))
    freezer.move_to("2026-01-15 13:00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["mode"] == []
    assert hass.states.get("sensor.hallway_open_windows_and_doors") is None


async def test_open_window_works_even_without_an_outdoor_reading(
    hass: HomeAssistant, calls, freezer
) -> None:
    for w in (WIN1, WIN2, PATIO):
        contact(hass, w, "on")
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-01-15 12:00:00")
    hass.states.async_set(WEATHER, "unavailable")
    set_climate(hass, "heat", hvac_modes=MODES, temperature=22.0)
    await setup(hass, make_entry(hass, contact_options(**{CONF_CONTACT_DELAY: 0})))
    assert [c.data["hvac_mode"] for c in calls["mode"]] == ["off"]


async def test_options_contacts_saved(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "contacts")
    assert result["type"] is FlowResultType.FORM
    ok = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CONTACTS_ENABLED: True,
            CONF_CONTACT_SOURCES: [WIN1, PATIO],
            CONF_CONTACT_DELAY: 5,
        },
    )
    assert ok["type"] is FlowResultType.MENU
    await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "save"})
    assert entry.options[CONF_CONTACTS_ENABLED] is True
    assert entry.options[CONF_CONTACT_SOURCES] == [WIN1, PATIO]
    assert entry.options[CONF_CONTACT_DELAY] == 5


# ---------------------------------------------------------------------------
# Safety temperatures (indoor only)
# ---------------------------------------------------------------------------


ROOM = "sensor.bedroom_temperature"


def safety_options(**extra):
    return {CONF_SAFETY_ENABLED: True, CONF_SAFETY_HOT: 30.0, CONF_SAFETY_COLD: 10.0, **extra}


async def test_too_hot_indoors_turns_the_air_conditioning_on(
    hass: HomeAssistant, calls
) -> None:
    set_weather(hass, 5)  # cold outside, but the house is hot
    set_climate(hass, "heat", hvac_modes=MODES, temperature=22.0, current_temperature=31.0)
    await setup(hass, make_entry(hass, safety_options()))
    assert calls["mode"][-1].data["hvac_mode"] == "cool"
    assert calls["temp"][-1].data["temperature"] == 28.0
    assert hass.states.get("sensor.hallway_status").state == "safety_too_hot"


async def test_too_cold_indoors_turns_the_heating_on(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 25)  # warm outside, but the house is cold
    set_climate(hass, "off", hvac_modes=MODES, current_temperature=9.0)
    await setup(hass, make_entry(hass, safety_options()))
    assert calls["mode"][-1].data["hvac_mode"] == "heat"
    assert calls["temp"][-1].data["temperature"] == 12.0
    assert hass.states.get("sensor.hallway_status").state == "safety_too_cold"


async def test_normal_indoor_temperature_changes_nothing(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 0)
    set_climate(hass, "off", hvac_modes=MODES, current_temperature=21.0)
    await setup(hass, make_entry(hass, safety_options()))
    assert hass.states.get("sensor.hallway_status").state == "following_curve"


async def test_safety_beats_windows_away_pause_and_switches(
    hass: HomeAssistant, calls, freezer
) -> None:
    phone(hass, ALICE, "far")
    contact(hass, WIN1, "on")
    set_weather(hass, 5)
    set_climate(hass, "off", hvac_modes=MODES, current_temperature=32.0)
    entry = make_entry(
        hass,
        {
            **safety_options(),
            **away_options(**{CONF_PRESENCE_DELAY: 0, CONF_PRESENCE_SOURCES: [ALICE]}),
            **contact_options(**{CONF_CONTACT_DELAY: 0, CONF_CONTACT_SOURCES: [WIN1]}),
            CONF_COOL_ENABLED: False,
        },
    )
    await setup(hass, entry)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.hallway_enabled"}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.hallway_windows_open"}, blocking=True
    )
    assert calls["mode"][-1].data["hvac_mode"] == "cool"
    assert hass.states.get("sensor.hallway_status").state == "safety_too_hot"


async def test_safety_holds_until_the_house_has_recovered(
    hass: HomeAssistant, calls
) -> None:
    set_weather(hass, 5)
    set_climate(hass, "heat", hvac_modes=MODES, temperature=22.0, current_temperature=31.0)
    await setup(hass, make_entry(hass, safety_options()))
    set_climate(hass, "cool", hvac_modes=MODES, temperature=28.0, current_temperature=29.0)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=61))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.hallway_status").state == "safety_too_hot"  # 29 > 28
    set_climate(hass, "cool", hvac_modes=MODES, temperature=28.0, current_temperature=27.5)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=122))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.hallway_status").state == "following_curve"


async def test_safety_reacts_without_waiting_for_the_interval(
    hass: HomeAssistant, calls
) -> None:
    set_weather(hass, 5)
    set_climate(hass, "heat", hvac_modes=MODES, temperature=22.0, current_temperature=21.0)
    await setup(hass, make_entry(hass, safety_options()))
    assert hass.states.get("sensor.hallway_status").state == "following_curve"
    set_climate(hass, "heat", hvac_modes=MODES, temperature=22.0, current_temperature=30.5)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.hallway_status").state == "safety_too_hot"


async def test_extra_room_sensor_can_trigger_safety(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 5)
    hass.states.async_set(ROOM, "31", {"unit_of_measurement": "°C"})
    set_climate(hass, "heat", hvac_modes=MODES, temperature=22.0, current_temperature=21.0)
    await setup(hass, make_entry(hass, safety_options(**{CONF_SAFETY_SENSORS: [ROOM]})))
    assert hass.states.get("sensor.hallway_status").state == "safety_too_hot"


async def test_safety_works_without_an_outdoor_reading(hass: HomeAssistant, calls) -> None:
    hass.states.async_set(WEATHER, "unavailable")
    set_climate(hass, "heat", hvac_modes=MODES, temperature=22.0, current_temperature=31.0)
    await setup(hass, make_entry(hass, safety_options()))
    assert calls["mode"][-1].data["hvac_mode"] == "cool"


async def test_safety_off_by_default(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 5)
    set_climate(hass, "heat", hvac_modes=MODES, temperature=22.0, current_temperature=40.0)
    await setup(hass, make_entry(hass))
    assert hass.states.get("sensor.hallway_status").state == "following_curve"


async def test_safety_in_fahrenheit_system(hass: HomeAssistant, calls) -> None:
    hass.config.units = US_CUSTOMARY_SYSTEM
    set_weather(hass, 40, "°F")
    set_climate(
        hass, "heat", hvac_modes=MODES, temperature=70, current_temperature=88, min_temp=45, max_temp=95
    )  # 31 C
    await setup(hass, make_entry(hass, safety_options()))
    assert hass.states.get("sensor.hallway_status").state == "safety_too_hot"
    assert calls["temp"][-1].data["temperature"] == 82.5  # 28 C, on the thermostat's 0.5 F step


async def test_options_safety_saved_and_validated(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "safety")
    flow_id = result["flow_id"]
    base = {
        CONF_SAFETY_ENABLED: True,
        CONF_SAFETY_HOT: 32,
        CONF_SAFETY_COLD: 8,
        CONF_SAFETY_SENSORS: [ROOM],
    }
    bad = await hass.config_entries.options.async_configure(
        flow_id, {**base, CONF_SAFETY_HOT: 12, CONF_SAFETY_COLD: 10}
    )
    assert bad["errors"] == {"base": "safety_order"}
    ok = await hass.config_entries.options.async_configure(flow_id, base)
    assert ok["type"] is FlowResultType.MENU
    await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert entry.options[CONF_SAFETY_ENABLED] is True
    assert entry.options[CONF_SAFETY_HOT] == 32.0
    assert entry.options[CONF_SAFETY_COLD] == 8.0
    assert entry.options[CONF_SAFETY_SENSORS] == [ROOM]


# ---------------------------------------------------------------------------
# Indoor sensors: weights, replacing the thermostat reading, time windows
# ---------------------------------------------------------------------------


CRIB = "sensor.crib_temperature"
LIVING = "sensor.living_room_temperature"


def room(hass, entity_id, value, unit="°C"):
    hass.states.async_set(entity_id, str(value), {"unit_of_measurement": unit})


def indoor_options(sources, windows=None, weights=None, **extra):
    return {
        CONF_INDOOR_ENABLED: True,
        CONF_INDOOR_SOURCES: sources,
        CONF_INDOOR_WINDOWS: windows or [],
        CONF_INDOOR_WEIGHTS: weights or {},
        **extra,
    }


async def _indoor_setup(hass, freezer, options, thermostat=22.0, hour="12:00:00"):
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to(f"2026-01-15 {hour}")
    set_weather(hass, 0)  # the table wants 22
    set_climate(
        hass, "heat", hvac_modes=MODES, temperature=22.0, current_temperature=thermostat
    )
    await setup(hass, make_entry(hass, options))


async def test_another_sensor_replaces_the_thermostat_reading(
    hass: HomeAssistant, calls, freezer
) -> None:
    room(hass, CRIB, 20.0)  # the crib is 2 colder than the thermostat thinks
    await _indoor_setup(hass, freezer, indoor_options([CRIB]))
    assert calls["temp"][-1].data["temperature"] == 24.0  # 22 wanted + 2 shift
    sensor = hass.states.get("sensor.hallway_indoor_temperature")
    assert float(sensor.state) == 20.0
    assert sensor.attributes["target_shift_c"] == 2.0
    assert sensor.attributes["sources_and_weights"] == {CRIB: 1.0}


async def test_thermostat_is_only_used_when_it_is_in_the_list(
    hass: HomeAssistant, calls, freezer
) -> None:
    room(hass, CRIB, 20.0)
    await _indoor_setup(hass, freezer, indoor_options([CRIB]), thermostat=26.0)
    assert float(hass.states.get("sensor.hallway_indoor_temperature").state) == 20.0
    set_climate(hass, "heat", hvac_modes=MODES, temperature=22.0, current_temperature=26.0)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_INDOOR_SOURCES: [CRIB, CLIMATE]}
    )
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.hallway_indoor_temperature").state) == 23.0


async def test_weights_decide_how_much_each_sensor_counts(
    hass: HomeAssistant, calls, freezer
) -> None:
    room(hass, CRIB, 18.0)
    room(hass, LIVING, 22.0)
    # crib 18 (weight 3), living room 22 (weight 1) -> average 19; thermostat reads 22
    options = indoor_options([CRIB, LIVING], weights={CRIB: 3.0, LIVING: 1.0})
    await _indoor_setup(hass, freezer, options, thermostat=22.0)
    assert float(hass.states.get("sensor.hallway_indoor_temperature").state) == 19.0
    assert calls["temp"][-1].data["temperature"] == 25.0  # 22 + (22 - 19)


async def test_sensors_change_with_the_time_of_day(
    hass: HomeAssistant, calls, freezer
) -> None:
    room(hass, CRIB, 20.0)
    options = indoor_options(
        [CLIMATE], windows=[{"start": "20:00", "end": "07:00", "sources": [CRIB]}]
    )
    await _indoor_setup(hass, freezer, options, hour="12:00:00")
    assert calls["temp"] == []  # daytime: only the thermostat, nothing to shift
    set_climate(hass, "heat", hvac_modes=MODES, temperature=22.0, current_temperature=22.0)
    freezer.move_to("2026-01-15 20:00:01")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["temp"][-1].data["temperature"] == 24.0  # night: the crib sensor
    attrs = hass.states.get("sensor.hallway_indoor_temperature").attributes
    assert attrs["time_window"] == "20:00-07:00"


async def test_shift_is_capped(hass: HomeAssistant, calls, freezer) -> None:
    room(hass, CRIB, 10.0)  # a wild reading, 12 colder than the thermostat
    await _indoor_setup(hass, freezer, indoor_options([CRIB]))
    assert calls["temp"][-1].data["temperature"] == 25.0  # capped at +3


async def test_unavailable_sensor_falls_back_to_the_thermostat(
    hass: HomeAssistant, calls, freezer
) -> None:
    hass.states.async_set(CRIB, "unavailable")
    await _indoor_setup(hass, freezer, indoor_options([CRIB]))
    assert calls["temp"] == []  # no usable reading: nothing is shifted
    assert hass.states.get("sensor.hallway_indoor_temperature").state == "unknown"


async def test_one_dead_sensor_does_not_break_the_average(
    hass: HomeAssistant, calls, freezer
) -> None:
    hass.states.async_set(CRIB, "unavailable")
    room(hass, LIVING, 21.0)
    await _indoor_setup(hass, freezer, indoor_options([CRIB, LIVING]))
    assert float(hass.states.get("sensor.hallway_indoor_temperature").state) == 21.0
    assert calls["temp"][-1].data["temperature"] == 23.0


async def test_sensor_change_updates_the_target_without_waiting(
    hass: HomeAssistant, calls, freezer
) -> None:
    room(hass, CRIB, 22.0)
    await _indoor_setup(hass, freezer, indoor_options([CRIB]))
    assert calls["temp"] == []
    room(hass, CRIB, 20.0)
    await hass.async_block_till_done()
    assert calls["temp"][-1].data["temperature"] == 24.0


async def test_indoor_sensors_off_by_default(hass: HomeAssistant, calls, freezer) -> None:
    room(hass, CRIB, 18.0)
    await _indoor_setup(
        hass, freezer, indoor_options([CRIB], **{CONF_INDOOR_ENABLED: False})
    )
    assert calls["temp"] == []
    assert hass.states.get("sensor.hallway_indoor_temperature") is None


async def _step(hass, flow_id, user_input=None):
    return await hass.config_entries.options.async_configure(flow_id, user_input)


async def test_options_indoor_windows_can_be_added_changed_and_removed(
    hass: HomeAssistant,
) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "indoor")
    flow_id = result["flow_id"]
    result = await _step(
        hass,
        flow_id,
        {
            CONF_INDOOR_ENABLED: True,
            CONF_INDOOR_SOURCES: [CLIMATE, LIVING],
            CONF_INDOOR_MAX_OFFSET: 2.5,
        },
    )
    # No windows to start with: the menu offers only "add" and "done".
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["indoor_window_add", "indoor_done"]

    # A window needs a sensor and different start and end times.
    result = await _step(hass, flow_id, {"next_step_id": "indoor_window_add"})
    bad = await _step(hass, flow_id, {"start": "20:00:00", "end": "07:00:00", "sources": []})
    assert bad["errors"] == {"base": "indoor_window_needs_sensor"}
    bad = await _step(hass, flow_id, {"start": "20:00:00", "end": "20:00:00", "sources": [CRIB]})
    assert bad["errors"] == {"base": "indoor_same_time"}
    result = await _step(hass, flow_id, {"start": "20:00:00", "end": "07:00:00", "sources": [CRIB]})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == [
        "indoor_window_add",
        "indoor_window_pick",
        "indoor_done",
    ]

    # As many as wanted: add a second and a third.
    for start, end, sensor in (("13:00:00", "15:00:00", LIVING), ("09:00:00", "11:00:00", CRIB)):
        await _step(hass, flow_id, {"next_step_id": "indoor_window_add"})
        await _step(hass, flow_id, {"start": start, "end": end, "sources": [sensor]})

    # Change the second window, then remove the third.
    await _step(hass, flow_id, {"next_step_id": "indoor_window_pick"})
    await _step(hass, flow_id, {"window": "1"})
    await _step(
        hass,
        flow_id,
        {"start": "12:00:00", "end": "16:00:00", "sources": [LIVING], "remove": False},
    )
    await _step(hass, flow_id, {"next_step_id": "indoor_window_pick"})
    await _step(hass, flow_id, {"window": "2"})
    await _step(
        hass,
        flow_id,
        {"start": "09:00:00", "end": "11:00:00", "sources": [CRIB], "remove": True},
    )

    # Done: several sensors are in play, so the weights page comes next.
    weights = await _step(hass, flow_id, {"next_step_id": "indoor_done"})
    assert weights["type"] is FlowResultType.FORM
    assert weights["step_id"] == "indoor_weights"
    done = await _step(hass, flow_id, {CLIMATE: 0.5, LIVING: 2.0, CRIB: 3.0})
    assert done["type"] is FlowResultType.MENU
    await _step(hass, flow_id, {"next_step_id": "save"})
    assert entry.options[CONF_INDOOR_ENABLED] is True
    assert entry.options[CONF_INDOOR_SOURCES] == [CLIMATE, LIVING]
    assert entry.options[CONF_INDOOR_WINDOWS] == [
        {"start": "20:00", "end": "07:00", "sources": [CRIB]},
        {"start": "12:00", "end": "16:00", "sources": [LIVING]},
    ]
    assert entry.options[CONF_INDOOR_WEIGHTS] == {CLIMATE: 0.5, LIVING: 2.0, CRIB: 3.0}
    assert entry.options[CONF_INDOOR_MAX_OFFSET] == 2.5


async def test_options_indoor_single_sensor_skips_the_weights_step(
    hass: HomeAssistant,
) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "indoor")
    flow_id = result["flow_id"]
    await _step(
        hass,
        flow_id,
        {CONF_INDOOR_ENABLED: True, CONF_INDOOR_SOURCES: [CRIB], CONF_INDOOR_MAX_OFFSET: 3.0},
    )
    done = await _step(hass, flow_id, {"next_step_id": "indoor_done"})
    assert done["type"] is FlowResultType.MENU
    assert done["step_id"] == "init"


async def test_indoor_windows_beyond_two_are_all_used(
    hass: HomeAssistant, calls, freezer
) -> None:
    room(hass, CRIB, 20.0)
    room(hass, LIVING, 19.0)
    windows = [
        {"start": "01:00", "end": "02:00", "sources": [LIVING]},
        {"start": "03:00", "end": "04:00", "sources": [LIVING]},
        {"start": "11:00", "end": "13:00", "sources": [CRIB]},
    ]
    await _indoor_setup(hass, freezer, indoor_options([], windows=windows), hour="12:00:00")
    assert calls["temp"][-1].data["temperature"] == 24.0  # the third window's crib sensor


async def test_resuming_the_program_keeps_the_thermostat_off_while_a_window_is_open(
    hass: HomeAssistant, calls, freezer
) -> None:
    contact(hass, WIN1, "off")
    contact(hass, PATIO, "off")
    options = contact_options(**{CONF_CONTACT_SOURCES: [WIN1, PATIO], CONF_CONTACT_DELAY: 0})
    await _contact_setup(hass, freezer, options)
    await hass.services.async_call(
        "cozy_control",
        "windows_opened",
        {"entity_id": "switch.hallway_windows_open", "hours": 1},
        blocking=True,
    )
    assert calls["mode"][-1].data["hvac_mode"] == "off"
    contact(hass, PATIO, "on")  # the patio door is still open when the hour is up
    await hass.async_block_till_done()
    freezer.move_to("2026-01-15 13:05:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("switch.hallway_windows_open").state == "off"  # program resumed
    assert hass.states.get("sensor.hallway_status").state == "door_or_window_open"
    assert all(c.data["hvac_mode"] == "off" for c in calls["mode"])  # never switched back on
    set_climate(hass, "off", hvac_modes=MODES)  # the mocked service does not change the state
    contact(hass, PATIO, "off")
    await hass.async_block_till_done()
    freezer.move_to("2026-01-15 13:06:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["mode"][-1].data["hvac_mode"] == "heat"


# ---------------------------------------------------------------------------
# Several weighted outdoor sources
# ---------------------------------------------------------------------------


YARD = "sensor.yard_temperature"
ROOF = "sensor.roof_temperature"


def outdoor_options(sources, weights=None):
    return {CONF_OUTDOOR_SOURCES: sources, CONF_OUTDOOR_WEIGHTS: weights or {}}


async def test_outdoor_sources_are_averaged_with_weights(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 0)  # the weather service says 0
    room(hass, YARD, 8.0)  # your own sensor says 8
    set_climate(hass, "off", hvac_modes=MODES)
    options = outdoor_options([WEATHER, YARD], {WEATHER: 1.0, YARD: 3.0})  # (0 + 24) / 4 = 6
    await setup(hass, make_entry(hass, options))
    sensor = hass.states.get("sensor.hallway_outdoor_temperature")
    assert float(sensor.state) == 6.0
    assert sensor.attributes["sources_and_weights"] == {WEATHER: 1.0, YARD: 3.0}


async def test_outdoor_sources_mix_units(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    room(hass, YARD, 68.0, "°F")  # 20 C
    set_climate(hass, "off", hvac_modes=MODES)
    await setup(hass, make_entry(hass, outdoor_options([WEATHER, YARD])))
    assert float(hass.states.get("sensor.hallway_outdoor_temperature").state) == 15.0


async def test_unavailable_outdoor_source_is_skipped(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    hass.states.async_set(YARD, "unavailable")
    set_climate(hass, "off", hvac_modes=MODES)
    await setup(hass, make_entry(hass, outdoor_options([WEATHER, YARD], {YARD: 5.0})))
    assert float(hass.states.get("sensor.hallway_outdoor_temperature").state) == 10.0
    assert hass.states.get("sensor.hallway_status").state == "following_curve"


async def test_all_outdoor_sources_unavailable(hass: HomeAssistant, calls) -> None:
    hass.states.async_set(WEATHER, "unavailable")
    hass.states.async_set(YARD, "unavailable")
    set_climate(hass, "off", hvac_modes=MODES)
    await setup(hass, make_entry(hass, outdoor_options([WEATHER, YARD])))
    assert hass.states.get("sensor.hallway_status").state == "source_unavailable"


async def test_a_zero_weight_ignores_a_source(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    room(hass, YARD, 30.0)
    set_climate(hass, "off", hvac_modes=MODES)
    await setup(hass, make_entry(hass, outdoor_options([WEATHER, YARD], {YARD: 0.0})))
    assert float(hass.states.get("sensor.hallway_outdoor_temperature").state) == 10.0


async def test_old_entries_with_one_source_still_work(hass: HomeAssistant, calls) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off", hvac_modes=MODES)
    await setup(hass, make_entry(hass))  # no outdoor_sources option at all
    assert float(hass.states.get("sensor.hallway_outdoor_temperature").state) == 10.0


async def test_options_outdoor_sources_and_weights_saved(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "general")
    flow_id = result["flow_id"]
    base = {
        "update_interval": 60,
        CONF_UNIT: "celsius",
        "min_change": 0.5,
        "range_width": 2.0,
        "interpolate": True,
    }
    bad = await hass.config_entries.options.async_configure(
        flow_id, {**base, CONF_OUTDOOR_SOURCES: []}
    )
    assert bad["errors"] == {"base": "outdoor_needs_source"}
    weights = await hass.config_entries.options.async_configure(
        flow_id, {**base, CONF_OUTDOOR_SOURCES: [YARD, WEATHER]}
    )
    assert weights["type"] is FlowResultType.FORM and weights["step_id"] == "outdoor_weights"
    done = await hass.config_entries.options.async_configure(flow_id, {YARD: 3.0, WEATHER: 1.0})
    assert done["type"] is FlowResultType.MENU
    await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert entry.options[CONF_OUTDOOR_SOURCES] == [YARD, WEATHER]
    assert entry.options[CONF_OUTDOOR_WEIGHTS] == {YARD: 3.0, WEATHER: 1.0}
    assert entry.data[CONF_WEATHER] == YARD


async def test_one_outdoor_source_skips_the_weights_page(hass: HomeAssistant) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off")
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await _open_section(hass, entry, "general")
    done = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_OUTDOOR_SOURCES: [WEATHER],
            "update_interval": 60,
            CONF_UNIT: "celsius",
            "min_change": 0.5,
            "range_width": 2.0,
            "interpolate": True,
        },
    )
    assert done["type"] is FlowResultType.MENU


# ---------------------------------------------------------------------------
# Starting up after a reboot or a power cut
# ---------------------------------------------------------------------------


async def test_catches_up_when_the_weather_arrives_after_startup(
    hass: HomeAssistant, calls, freezer
) -> None:
    # After a reboot the weather integration may load later than this one.
    freezer.move_to("2026-01-15 12:00:00")
    hass.states.async_set(WEATHER, "unavailable")
    set_climate(hass, "off", hvac_modes=MODES)
    await setup(hass, make_entry(hass))
    assert hass.states.get("sensor.hallway_status").state == "source_unavailable"
    set_weather(hass, 10)
    freezer.move_to("2026-01-15 12:02:00")  # far less than the 60 minute interval
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.hallway_status").state == "following_curve"
    assert calls["mode"][-1].data["hvac_mode"] == "heat"


async def test_catches_up_when_the_thermostat_arrives_after_startup(
    hass: HomeAssistant, calls, freezer
) -> None:
    freezer.move_to("2026-01-15 12:00:00")
    set_weather(hass, 10)
    hass.states.async_set(CLIMATE, "unavailable")
    await setup(hass, make_entry(hass))
    assert hass.states.get("sensor.hallway_status").state == "thermostat_unavailable"
    set_climate(hass, "off", hvac_modes=MODES)
    freezer.move_to("2026-01-15 12:02:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.hallway_status").state == "following_curve"


async def test_keeps_retrying_while_the_thermostat_is_offline(
    hass: HomeAssistant, calls, freezer
) -> None:
    # A power or internet cut: the thermostat stays offline for a while.
    freezer.move_to("2026-01-15 12:00:00")
    set_weather(hass, 10)
    hass.states.async_set(CLIMATE, "unavailable")
    await setup(hass, make_entry(hass))
    for minute in (2, 4, 6):
        freezer.move_to(f"2026-01-15 12:0{minute}:00")
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert hass.states.get("sensor.hallway_status").state == "thermostat_unavailable"
    set_climate(hass, "off", hvac_modes=MODES)
    freezer.move_to("2026-01-15 12:08:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.hallway_status").state == "following_curve"


async def test_settings_pause_and_open_windows_survive_a_restart(
    hass: HomeAssistant, calls
) -> None:
    set_weather(hass, 10)
    set_climate(hass, "off", hvac_modes=MODES)
    entry = make_entry(hass)
    await setup(hass, entry)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.hallway_windows_open"}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.hallway_enabled"}, blocking=True
    )
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.hallway_windows_open").state == "on"
    assert hass.states.get("switch.hallway_enabled").state == "off"
