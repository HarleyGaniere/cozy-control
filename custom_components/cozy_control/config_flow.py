"""Config flow and settings menus for Cozy Control."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TimeSelector,
)

from . import engine
from .const import (
    CONF_AWAY_ENABLED,
    CONF_AWAY_SETPOINTS,
    CONF_BED_ENABLED,
    CONF_BED_END,
    CONF_BED_SETPOINTS,
    CONF_BED_START,
    CONF_BRIEF_DATES,
    CONF_BRIEF_DATES_ENABLED,
    CONF_CLIMATE,
    CONF_COLD_AT,
    CONF_CONTACT_DELAY,
    CONF_CONTACT_SOURCES,
    CONF_CONTACTS_ENABLED,
    CONF_COOL_DATES_ENABLED,
    CONF_COOL_DISABLED,
    CONF_COOL_ENABLED,
    CONF_HEAT_DATES_ENABLED,
    CONF_HEAT_DISABLED,
    CONF_HEAT_ENABLED,
    CONF_HOT_AT,
    CONF_INDOOR_ENABLED,
    CONF_INDOOR_MAX_OFFSET,
    CONF_INDOOR_SOURCES,
    CONF_INDOOR_WEIGHTS,
    CONF_INDOOR_WINDOWS,
    CONF_INTERPOLATE,
    CONF_INTERVAL,
    CONF_MIN_CHANGE,
    CONF_OFF_ENABLED,
    CONF_OFF_MAX,
    CONF_OFF_MIN,
    CONF_OUTDOOR_SOURCES,
    CONF_OUTDOOR_WEIGHTS,
    CONF_PRESENCE_DELAY,
    CONF_PRESENCE_MAX_ACCURACY,
    CONF_PRESENCE_RADIUS,
    CONF_PRESENCE_SOURCES,
    CONF_RANGE_WIDTH,
    CONF_SAFETY_COLD,
    CONF_SAFETY_ENABLED,
    CONF_SAFETY_HOT,
    CONF_SAFETY_SENSORS,
    CONF_SETPOINTS,
    CONF_TIME_FORMAT,
    CONF_UNIT,
    CONF_USE_FORECAST,
    CONF_WEATHER,
    CONF_WIN_HIGH,
    CONF_WIN_LOW,
    CONF_WIN_MAX_HOURS,
    CONF_WIN_RESUME,
    DEFAULT_AWAY_SETPOINTS,
    DEFAULT_BED_END,
    DEFAULT_BED_SETPOINTS,
    DEFAULT_BED_START,
    DEFAULT_CONTACT_DELAY,
    DEFAULT_INDOOR_MAX_OFFSET,
    DEFAULT_INDOOR_WINDOW,
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
    TIME_12H,
    TIME_24H,
    UNIT_CELSIUS,
    UNIT_FAHRENHEIT,
    UNIT_SYSTEM,
    dates_enabled,
    default_options,
    display_unit,
    outdoor_sources,
)

# Outdoor sources: any weather entity, or any temperature sensor.
_OUTDOOR_FILTER = [{"domain": "weather"}, {"domain": "sensor", "device_class": "temperature"}]
SOURCE_SELECTOR = EntitySelector(EntitySelectorConfig(filter=_OUTDOOR_FILTER))
SOURCES_SELECTOR = EntitySelector(EntitySelectorConfig(filter=_OUTDOOR_FILTER, multiple=True))
CLIMATE_SELECTOR = EntitySelector(EntitySelectorConfig(domain="climate"))
INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=1, max=1440, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="min"
    )
)

# Sanity limits for what a person could mean, in Celsius.
_MIN_C, _MAX_C = -80.0, 60.0


def _delta_selector(unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0, max=20, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement=unit
        )
    )


def _temp_selector(unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=-100, max=150, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement=unit
        )
    )


class CozyControlConfigFlow(ConfigFlow, domain=DOMAIN):
    """First-time setup: which weather source and which thermostat."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_CLIMATE])
            self._abort_if_unique_id_configured()
            options = default_options()
            options[CONF_INTERVAL] = int(user_input.pop(CONF_INTERVAL))
            name = user_input.pop("name")
            return self.async_create_entry(title=name, data=user_input, options=options)

        schema = vol.Schema(
            {
                vol.Required("name", default="Cozy Control"): str,
                vol.Required(CONF_WEATHER): SOURCE_SELECTOR,
                vol.Required(CONF_CLIMATE): CLIMATE_SELECTOR,
                vol.Required(CONF_INTERVAL, default=DEFAULT_INTERVAL): INTERVAL_SELECTOR,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CozyControlOptionsFlow()


class CozyControlOptionsFlow(OptionsFlow):
    """Settings menu. Changes are collected and saved when the user picks Save."""

    def __init__(self) -> None:
        self._options: dict[str, Any] | None = None
        self._data: dict[str, Any] | None = None

    # The entry is only available once the flow is attached to it.
    def _load(self) -> None:
        if self._options is None:
            self._options = dict(self.config_entry.options)
            self._data = dict(self.config_entry.data)

    @property
    def _unit(self) -> str:
        return display_unit(self.hass, self._options)

    # -- menu -----------------------------------------------------------------

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._load()
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "general",
                "setpoints",
                "bedtime",
                "presence",
                "away_temps",
                "contacts",
                "indoor",
                "safety",
                "off_range",
                "seasons",
                "windows",
                "heat_cool",
                "save",
            ],
        )

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._load()
        if self._data != dict(self.config_entry.data):
            self.hass.config_entries.async_update_entry(self.config_entry, data=self._data)
        return self.async_create_entry(data=self._options)

    # -- general ---------------------------------------------------------------

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        o = self._options
        errors: dict[str, str] = {}
        if user_input is not None and not user_input.get(CONF_OUTDOOR_SOURCES):
            errors["base"] = "outdoor_needs_source"
        elif user_input is not None:
            old_unit = self._unit
            chosen = list(user_input[CONF_OUTDOOR_SOURCES])
            o[CONF_OUTDOOR_SOURCES] = chosen
            self._data[CONF_WEATHER] = chosen[0]
            o[CONF_INTERVAL] = int(user_input[CONF_INTERVAL])
            o[CONF_UNIT] = user_input[CONF_UNIT]
            o[CONF_TIME_FORMAT] = user_input[CONF_TIME_FORMAT]
            o[CONF_INTERPOLATE] = bool(user_input[CONF_INTERPOLATE])
            # Delta fields are shown in the unit that was active when the form was opened.
            o[CONF_MIN_CHANGE] = engine.delta_to_celsius(
                float(user_input[CONF_MIN_CHANGE]), old_unit
            )
            o[CONF_RANGE_WIDTH] = engine.delta_to_celsius(
                float(user_input[CONF_RANGE_WIDTH]), old_unit
            )
            if len(chosen) > 1:
                return await self.async_step_outdoor_weights()
            return await self.async_step_init()

        unit = self._unit
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_OUTDOOR_SOURCES,
                    default=(user_input or {}).get(
                        CONF_OUTDOOR_SOURCES, outdoor_sources(self.config_entry)
                    ),
                ): SOURCES_SELECTOR,
                vol.Required(
                    CONF_INTERVAL, default=o.get(CONF_INTERVAL, DEFAULT_INTERVAL)
                ): INTERVAL_SELECTOR,
                vol.Required(CONF_UNIT, default=o.get(CONF_UNIT, UNIT_SYSTEM)): SelectSelector(
                    SelectSelectorConfig(
                        options=[UNIT_SYSTEM, UNIT_CELSIUS, UNIT_FAHRENHEIT],
                        translation_key="unit",
                    )
                ),
                vol.Required(
                    CONF_TIME_FORMAT, default=o.get(CONF_TIME_FORMAT, TIME_24H)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[TIME_24H, TIME_12H], translation_key="time_format"
                    )
                ),
                vol.Required(
                    CONF_MIN_CHANGE,
                    default=round(
                        engine.delta_from_celsius(
                            o.get(CONF_MIN_CHANGE, DEFAULT_MIN_CHANGE), unit
                        ),
                        2,
                    ),
                ): _delta_selector(unit),
                vol.Required(
                    CONF_RANGE_WIDTH,
                    default=round(
                        engine.delta_from_celsius(
                            o.get(CONF_RANGE_WIDTH, DEFAULT_RANGE_WIDTH), unit
                        ),
                        2,
                    ),
                ): _delta_selector(unit),
                vol.Required(CONF_INTERPOLATE, default=o.get(CONF_INTERPOLATE, True)): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="general",
            data_schema=schema,
            errors=errors,
            description_placeholders={"unit": unit},
        )

    async def async_step_outdoor_weights(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """How much each outdoor source counts. A bigger number means more influence."""
        self._load()
        o = self._options
        chosen = list(o.get(CONF_OUTDOOR_SOURCES, []))
        if user_input is not None:
            o[CONF_OUTDOOR_WEIGHTS] = {e: float(user_input[e]) for e in chosen}
            return await self.async_step_init()
        weights = o.get(CONF_OUTDOOR_WEIGHTS, {})
        schema = vol.Schema(
            {
                vol.Required(e, default=float(weights.get(e, 1.0))): NumberSelector(
                    NumberSelectorConfig(min=0, max=10, step=0.1, mode=NumberSelectorMode.BOX)
                )
                for e in chosen
            }
        )
        return self.async_show_form(step_id="outdoor_weights", data_schema=schema)

    # -- setpoint table -------------------------------------------------------

    def _table_text(self, key: str = CONF_SETPOINTS) -> str:
        unit = self._unit
        fallback = {
            CONF_BED_SETPOINTS: DEFAULT_BED_SETPOINTS,
            CONF_AWAY_SETPOINTS: DEFAULT_AWAY_SETPOINTS,
        }.get(key, DEFAULT_SETPOINTS)
        points = [
            (engine.from_celsius(o, unit), engine.from_celsius(i, unit))
            for o, i in self._options.get(key, fallback)
        ]
        return engine.format_setpoints(points)

    @staticmethod
    def _example(unit: str) -> dict[str, str]:
        """Example row for the table description, in the unit being edited."""
        outside, inside = (32, 72) if unit == engine.UNIT_F else (0, 22)
        return {
            "example": f"{outside}: {inside}",
            "example_outside": str(outside),
            "example_inside": str(inside),
        }

    async def async_step_setpoints(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        errors: dict[str, str] = {}
        unit = self._unit
        if user_input is not None:
            text = user_input[CONF_SETPOINTS]
            if text.strip() == self._table_text().strip():
                return await self.async_step_init()  # unchanged: keep exact stored values
            try:
                points = engine.parse_setpoints(text)
                celsius = [
                    [engine.to_celsius(o, unit), engine.to_celsius(i, unit)] for o, i in points
                ]
                if any(not _MIN_C <= v <= _MAX_C for pair in celsius for v in pair):
                    raise ValueError("out of range")
            except ValueError as err:
                errors["base"] = "invalid_table"
                placeholders = {"unit": unit, "error": str(err), **self._example(unit)}
            else:
                self._options[CONF_SETPOINTS] = celsius
                return await self.async_step_init()
        else:
            placeholders = {"unit": unit, "error": "", **self._example(unit)}

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SETPOINTS,
                    default=(user_input or {}).get(CONF_SETPOINTS, self._table_text()),
                ): TextSelector(TextSelectorConfig(multiline=True))
            }
        )
        return self.async_show_form(
            step_id="setpoints",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    def _clock_text(self, key: str, default: str) -> str:
        """A stored bedtime time, written in the chosen time format."""
        hour12 = self._options.get(CONF_TIME_FORMAT, TIME_24H) == TIME_12H
        try:
            return engine.format_clock(engine.parse_clock(self._options.get(key, default)), hour12)
        except ValueError:
            return default

    # -- bedtime --------------------------------------------------------------

    async def async_step_bedtime(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        o = self._options
        unit = self._unit
        errors: dict[str, str] = {}
        hour12 = o.get(CONF_TIME_FORMAT, TIME_24H) == TIME_12H
        placeholders = {
            "unit": unit,
            "error": "",
            "time_example": "8:00 PM to 5:00 AM" if hour12 else "20:00 to 05:00",
            **self._example(unit),
        }
        if user_input is not None:
            text = user_input[CONF_BED_SETPOINTS]
            try:
                start = engine.parse_clock(user_input[CONF_BED_START])
                end = engine.parse_clock(user_input[CONF_BED_END])
            except ValueError as err:
                errors["base"] = "invalid_time"
                placeholders["error"] = str(err)
            else:
                if user_input[CONF_BED_ENABLED] and start == end:
                    errors["base"] = "bedtime_same_time"
            if not errors:
                celsius = None
                if text.strip() != self._table_text(CONF_BED_SETPOINTS).strip():
                    try:
                        points = engine.parse_setpoints(text)
                        celsius = [
                            [engine.to_celsius(a, unit), engine.to_celsius(b, unit)]
                            for a, b in points
                        ]
                        if any(not _MIN_C <= v <= _MAX_C for pair in celsius for v in pair):
                            raise ValueError("out of range")
                    except ValueError as err:
                        errors["base"] = "invalid_table"
                        placeholders["error"] = str(err)
                if not errors:
                    o[CONF_BED_ENABLED] = bool(user_input[CONF_BED_ENABLED])
                    o[CONF_BED_START] = engine.format_clock(start)  # stored as 24 hour HH:MM
                    o[CONF_BED_END] = engine.format_clock(end)
                    if celsius is not None:  # unchanged text keeps the exact stored values
                        o[CONF_BED_SETPOINTS] = celsius
                    return await self.async_step_init()

        given = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BED_ENABLED, default=given.get(CONF_BED_ENABLED, o.get(CONF_BED_ENABLED, False))
                ): BooleanSelector(),
                vol.Required(
                    CONF_BED_START,
                    default=given.get(CONF_BED_START, self._clock_text(CONF_BED_START, DEFAULT_BED_START)),
                ): str,
                vol.Required(
                    CONF_BED_END,
                    default=given.get(CONF_BED_END, self._clock_text(CONF_BED_END, DEFAULT_BED_END)),
                ): str,
                vol.Required(
                    CONF_BED_SETPOINTS,
                    default=given.get(CONF_BED_SETPOINTS, self._table_text(CONF_BED_SETPOINTS)),
                ): TextSelector(TextSelectorConfig(multiline=True)),
            }
        )
        return self.async_show_form(
            step_id="bedtime",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    # -- indoor temperature sources -------------------------------------------

    def _indoor_selector(self) -> EntitySelector:
        """Temperature sensors, plus thermostats (their own reading)."""
        return EntitySelector(
            EntitySelectorConfig(
                filter=[
                    {"domain": "sensor", "device_class": "temperature"},
                    {"domain": "climate"},
                ],
                multiple=True,
            )
        )

    @staticmethod
    def _window_label(window: dict[str, Any]) -> str:
        return f"{window['start']} to {window['end']}: {', '.join(window['sources'])}"

    async def async_step_indoor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        o = self._options
        unit = self._unit
        if user_input is not None:
            o[CONF_INDOOR_ENABLED] = bool(user_input[CONF_INDOOR_ENABLED])
            o[CONF_INDOOR_MAX_OFFSET] = engine.delta_to_celsius(
                float(user_input[CONF_INDOOR_MAX_OFFSET]), unit
            )
            o[CONF_INDOOR_SOURCES] = list(user_input.get(CONF_INDOOR_SOURCES, []))
            return await self.async_step_indoor_windows()

        shift = round(
            engine.delta_from_celsius(
                o.get(CONF_INDOOR_MAX_OFFSET, DEFAULT_INDOOR_MAX_OFFSET), unit
            ),
            1,
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_INDOOR_ENABLED, default=o.get(CONF_INDOOR_ENABLED, False)
                ): BooleanSelector(),
                vol.Optional(
                    CONF_INDOOR_SOURCES,
                    description={"suggested_value": o.get(CONF_INDOOR_SOURCES, [])},
                ): self._indoor_selector(),
                vol.Required(CONF_INDOOR_MAX_OFFSET, default=shift): _delta_selector(unit),
            }
        )
        return self.async_show_form(
            step_id="indoor", data_schema=schema, description_placeholders={"unit": unit}
        )

    async def async_step_indoor_windows(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """List the time windows and let the user add, change or remove them."""
        self._load()
        windows = self._options.get(CONF_INDOOR_WINDOWS, [])
        options = ["indoor_window_add"]
        if windows:
            options.append("indoor_window_pick")
        options.append("indoor_done")
        listing = "\n".join(f"• {self._window_label(w)}" for w in windows) or "None yet."
        return self.async_show_menu(
            step_id="indoor_windows",
            menu_options=options,
            description_placeholders={"windows": listing},
        )

    def _window_schema(self, window: dict[str, Any], editing: bool) -> vol.Schema:
        items: dict[Any, Any] = {
            vol.Required(
                "start", default=window.get("start", DEFAULT_INDOOR_WINDOW[0])
            ): TimeSelector(),
            vol.Required("end", default=window.get("end", DEFAULT_INDOOR_WINDOW[1])): TimeSelector(),
            vol.Optional(
                "sources", description={"suggested_value": window.get("sources", [])}
            ): self._indoor_selector(),
        }
        if editing:
            items[vol.Required("remove", default=False)] = BooleanSelector()
        return vol.Schema(items)

    def _read_window(self, user_input: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        """A window from the form, or an error key."""
        sources = list(user_input.get("sources", []))
        start = engine.parse_clock(user_input["start"])
        end = engine.parse_clock(user_input["end"])
        if not sources:
            return None, "indoor_window_needs_sensor"
        if start == end:
            return None, "indoor_same_time"
        return {
            "start": engine.format_clock(start),
            "end": engine.format_clock(end),
            "sources": sources,
        }, None

    async def async_step_indoor_window_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        errors: dict[str, str] = {}
        if user_input is not None:
            window, error = self._read_window(user_input)
            if window is not None:
                self._options.setdefault(CONF_INDOOR_WINDOWS, []).append(window)
                return await self.async_step_indoor_windows()
            errors["base"] = error or "indoor_same_time"
        return self.async_show_form(
            step_id="indoor_window_add",
            data_schema=self._window_schema(user_input or {}, editing=False),
            errors=errors,
        )

    async def async_step_indoor_window_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        windows = self._options.get(CONF_INDOOR_WINDOWS, [])
        if user_input is not None:
            self._edit_index = int(user_input["window"])
            return await self.async_step_indoor_window_edit()
        schema = vol.Schema(
            {
                vol.Required("window", default="0"): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": str(i), "label": self._window_label(w)}
                            for i, w in enumerate(windows)
                        ]
                    )
                )
            }
        )
        return self.async_show_form(step_id="indoor_window_pick", data_schema=schema)

    async def async_step_indoor_window_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        windows = self._options.setdefault(CONF_INDOOR_WINDOWS, [])
        index = getattr(self, "_edit_index", 0)
        if index >= len(windows):
            return await self.async_step_indoor_windows()
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("remove"):
                del windows[index]
                return await self.async_step_indoor_windows()
            window, error = self._read_window(user_input)
            if window is not None:
                windows[index] = window
                return await self.async_step_indoor_windows()
            errors["base"] = error or "indoor_same_time"
        return self.async_show_form(
            step_id="indoor_window_edit",
            data_schema=self._window_schema(user_input or windows[index], editing=True),
            errors=errors,
        )

    async def async_step_indoor_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for weights when more than one different sensor is in play, else go back to the menu."""
        self._load()
        o = self._options
        groups = [o.get(CONF_INDOOR_SOURCES, []), *(w["sources"] for w in o.get(CONF_INDOOR_WINDOWS, []))]
        if o.get(CONF_INDOOR_ENABLED) and len({e for g in groups for e in g}) > 1:
            return await self.async_step_indoor_weights()
        return await self.async_step_init()

    async def async_step_indoor_weights(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """How much each chosen sensor counts. A bigger number means more influence."""
        self._load()
        o = self._options
        chosen: list[str] = []
        for group in [o.get(CONF_INDOOR_SOURCES, []), *(w["sources"] for w in o.get(CONF_INDOOR_WINDOWS, []))]:
            for entity_id in group:
                if entity_id not in chosen:
                    chosen.append(entity_id)
        if user_input is not None:
            o[CONF_INDOOR_WEIGHTS] = {e: float(user_input[e]) for e in chosen}
            return await self.async_step_init()
        weights = o.get(CONF_INDOOR_WEIGHTS, {})
        schema = vol.Schema(
            {
                vol.Required(e, default=float(weights.get(e, 1.0))): NumberSelector(
                    NumberSelectorConfig(min=0, max=10, step=0.1, mode=NumberSelectorMode.BOX)
                )
                for e in chosen
            }
        )
        return self.async_show_form(step_id="indoor_weights", data_schema=schema)

    # -- safety temperatures --------------------------------------------------

    async def async_step_safety(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        o = self._options
        unit = self._unit
        defaults = engine.SafetySettings()
        errors: dict[str, str] = {}
        if user_input is not None:
            hot = engine.to_celsius(float(user_input[CONF_SAFETY_HOT]), unit)
            cold = engine.to_celsius(float(user_input[CONF_SAFETY_COLD]), unit)
            if not _MIN_C <= cold <= _MAX_C or not _MIN_C <= hot <= _MAX_C:
                errors["base"] = "safety_range"
            elif hot - cold < 4 * defaults.margin:
                errors["base"] = "safety_order"
            else:
                o[CONF_SAFETY_ENABLED] = bool(user_input[CONF_SAFETY_ENABLED])
                o[CONF_SAFETY_HOT] = hot
                o[CONF_SAFETY_COLD] = cold
                o[CONF_SAFETY_SENSORS] = list(user_input.get(CONF_SAFETY_SENSORS, []))
                return await self.async_step_init()

        given = user_input or {}

        def shown(key: str, fallback: float) -> float:
            if key in given:
                return given[key]
            return round(engine.from_celsius(o.get(key, fallback), unit), 1)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SAFETY_ENABLED,
                    default=given.get(CONF_SAFETY_ENABLED, o.get(CONF_SAFETY_ENABLED, False)),
                ): BooleanSelector(),
                vol.Required(
                    CONF_SAFETY_HOT, default=shown(CONF_SAFETY_HOT, defaults.hot)
                ): _temp_selector(unit),
                vol.Required(
                    CONF_SAFETY_COLD, default=shown(CONF_SAFETY_COLD, defaults.cold)
                ): _temp_selector(unit),
                vol.Optional(
                    CONF_SAFETY_SENSORS,
                    description={
                        "suggested_value": given.get(
                            CONF_SAFETY_SENSORS, o.get(CONF_SAFETY_SENSORS, [])
                        )
                    },
                ): EntitySelector(
                    EntitySelectorConfig(
                        filter=[{"domain": "sensor", "device_class": "temperature"}],
                        multiple=True,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="safety",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "unit": unit,
                "margin": str(
                    round(engine.delta_from_celsius(defaults.margin, unit), 1)
                ).rstrip("0").rstrip("."),
            },
        )

    # -- window and door sensors ----------------------------------------------

    async def async_step_contacts(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        o = self._options
        if user_input is not None:
            o[CONF_CONTACTS_ENABLED] = bool(user_input[CONF_CONTACTS_ENABLED])
            o[CONF_CONTACT_SOURCES] = list(user_input.get(CONF_CONTACT_SOURCES, []))
            o[CONF_CONTACT_DELAY] = int(user_input[CONF_CONTACT_DELAY])
            return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CONTACTS_ENABLED, default=o.get(CONF_CONTACTS_ENABLED, False)
                ): BooleanSelector(),
                vol.Optional(
                    CONF_CONTACT_SOURCES,
                    description={"suggested_value": o.get(CONF_CONTACT_SOURCES, [])},
                ): EntitySelector(
                    EntitySelectorConfig(
                        filter=[
                            {
                                "domain": "binary_sensor",
                                "device_class": ["window", "door", "opening", "garage_door"],
                            }
                        ],
                        multiple=True,
                    )
                ),
                vol.Required(
                    CONF_CONTACT_DELAY,
                    default=o.get(CONF_CONTACT_DELAY, DEFAULT_CONTACT_DELAY),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=120,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="contacts", data_schema=schema)

    # -- presence and away ----------------------------------------------------

    async def async_step_presence(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        o = self._options
        if user_input is not None:
            o[CONF_AWAY_ENABLED] = bool(user_input[CONF_AWAY_ENABLED])
            o[CONF_PRESENCE_SOURCES] = list(user_input.get(CONF_PRESENCE_SOURCES, []))
            o[CONF_PRESENCE_RADIUS] = int(user_input[CONF_PRESENCE_RADIUS])
            o[CONF_PRESENCE_DELAY] = int(user_input[CONF_PRESENCE_DELAY])
            o[CONF_PRESENCE_MAX_ACCURACY] = int(user_input[CONF_PRESENCE_MAX_ACCURACY])
            return await self.async_step_init()

        def metres(maximum: int) -> NumberSelector:
            return NumberSelector(
                NumberSelectorConfig(
                    min=10,
                    max=maximum,
                    step=10,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="m",
                )
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_AWAY_ENABLED, default=o.get(CONF_AWAY_ENABLED, False)
                ): BooleanSelector(),
                vol.Optional(
                    CONF_PRESENCE_SOURCES,
                    description={"suggested_value": o.get(CONF_PRESENCE_SOURCES, [])},
                ): EntitySelector(
                    EntitySelectorConfig(domain=["person", "device_tracker"], multiple=True)
                ),
                vol.Required(
                    CONF_PRESENCE_RADIUS,
                    default=o.get(CONF_PRESENCE_RADIUS, DEFAULT_PRESENCE_RADIUS),
                ): metres(5000),
                vol.Required(
                    CONF_PRESENCE_DELAY,
                    default=o.get(CONF_PRESENCE_DELAY, DEFAULT_PRESENCE_DELAY),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=240,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Required(
                    CONF_PRESENCE_MAX_ACCURACY,
                    default=o.get(CONF_PRESENCE_MAX_ACCURACY, DEFAULT_PRESENCE_MAX_ACCURACY),
                ): metres(2000),
            }
        )
        return self.async_show_form(step_id="presence", data_schema=schema)

    async def async_step_away_temps(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        errors: dict[str, str] = {}
        unit = self._unit
        placeholders = {"unit": unit, "error": "", **self._example(unit)}
        if user_input is not None:
            text = user_input[CONF_AWAY_SETPOINTS]
            if text.strip() == self._table_text(CONF_AWAY_SETPOINTS).strip():
                return await self.async_step_init()  # unchanged: keep exact stored values
            try:
                points = engine.parse_setpoints(text)
                celsius = [
                    [engine.to_celsius(a, unit), engine.to_celsius(b, unit)] for a, b in points
                ]
                if any(not _MIN_C <= v <= _MAX_C for pair in celsius for v in pair):
                    raise ValueError("out of range")
            except ValueError as err:
                errors["base"] = "invalid_table"
                placeholders["error"] = str(err)
            else:
                self._options[CONF_AWAY_SETPOINTS] = celsius
                return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_AWAY_SETPOINTS,
                    default=(user_input or {}).get(
                        CONF_AWAY_SETPOINTS, self._table_text(CONF_AWAY_SETPOINTS)
                    ),
                ): TextSelector(TextSelectorConfig(multiline=True))
            }
        )
        return self.async_show_form(
            step_id="away_temps",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    # -- off range ------------------------------------------------------------

    async def async_step_off_range(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        unit = self._unit
        o = self._options
        errors: dict[str, str] = {}
        was_on = bool(
            o.get(CONF_OFF_ENABLED, o.get(CONF_OFF_MIN) is not None and o.get(CONF_OFF_MAX) is not None)
        )
        if user_input is not None:
            on = bool(user_input.get(CONF_OFF_ENABLED, was_on))
            low, high = user_input.get(CONF_OFF_MIN), user_input.get(CONF_OFF_MAX)
            if (low is None) != (high is None):
                errors["base"] = "off_range_incomplete"
            elif low is None and on:
                errors["base"] = "off_range_needed"
            elif low is not None and float(low) > float(high):
                errors["base"] = "off_range_order"
            else:
                # The values are kept while switched off, so turning it back on is one click.
                o[CONF_OFF_ENABLED] = on
                for key, value in ((CONF_OFF_MIN, low), (CONF_OFF_MAX, high)):
                    if value is None:
                        o.pop(key, None)
                    else:
                        o[key] = engine.to_celsius(float(value), unit)
                return await self.async_step_init()

        def suggested(key: str) -> dict[str, Any]:
            value = (user_input or {}).get(key)
            if value is None and user_input is None and o.get(key) is not None:
                value = round(engine.from_celsius(o[key], unit), 1)
            return {"suggested_value": value}

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_OFF_ENABLED, default=(user_input or {}).get(CONF_OFF_ENABLED, was_on)
                ): BooleanSelector(),
                vol.Optional(CONF_OFF_MIN, description=suggested(CONF_OFF_MIN)): _temp_selector(unit),
                vol.Optional(CONF_OFF_MAX, description=suggested(CONF_OFF_MAX)): _temp_selector(unit),
            }
        )
        return self.async_show_form(
            step_id="off_range",
            data_schema=schema,
            errors=errors,
            description_placeholders={"unit": unit},
        )

    # -- windows and the morning briefing ---------------------------------------

    async def async_step_windows(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        o = self._options
        unit = self._unit
        defaults = engine.WindowSettings()
        errors: dict[str, str] = {}
        placeholders = {"unit": unit, "error": ""}
        temp_keys = {
            CONF_COLD_AT: defaults.cold_at,
            CONF_WIN_LOW: defaults.low,
            CONF_WIN_HIGH: defaults.high,
            CONF_HOT_AT: defaults.hot_at,
        }
        if user_input is not None:
            try:
                celsius = {
                    key: engine.to_celsius(float(user_input[key]), unit) for key in temp_keys
                }
                resume = engine.parse_clock(user_input[CONF_WIN_RESUME])
                dates = engine.parse_date_ranges(user_input.get(CONF_BRIEF_DATES, ""))
            except ValueError as err:
                errors["base"] = "invalid_windows_input"
                placeholders["error"] = str(err)
            else:
                ordered = [celsius[k] for k in temp_keys]
                if ordered != sorted(ordered):
                    errors["base"] = "window_order"
                else:
                    o.update(celsius)
                    o[CONF_WIN_RESUME] = engine.format_clock(resume)
                    o[CONF_WIN_MAX_HOURS] = float(user_input[CONF_WIN_MAX_HOURS])
                    o[CONF_USE_FORECAST] = bool(user_input[CONF_USE_FORECAST])
                    o[CONF_BRIEF_DATES_ENABLED] = bool(user_input[CONF_BRIEF_DATES_ENABLED])
                    o[CONF_BRIEF_DATES] = engine.format_date_ranges(dates)
                    return await self.async_step_init()

        given = user_input or {}

        def temp_default(key: str) -> float:
            if key in given:
                return given[key]
            return round(engine.from_celsius(o.get(key, temp_keys[key]), unit), 1)

        def stored(key: str, fallback: Any) -> Any:
            return given.get(key, o.get(key, fallback))

        items: dict[Any, Any] = {
            vol.Required(CONF_USE_FORECAST, default=stored(CONF_USE_FORECAST, True)): BooleanSelector(),
        }
        for key in (CONF_COLD_AT, CONF_WIN_LOW, CONF_WIN_HIGH, CONF_HOT_AT):
            items[vol.Required(key, default=temp_default(key))] = _temp_selector(unit)
        resume_default = given.get(
            CONF_WIN_RESUME, self._clock_text(CONF_WIN_RESUME, DEFAULT_WIN_RESUME)
        )
        items[vol.Required(CONF_WIN_RESUME, default=resume_default)] = str
        items[
            vol.Required(CONF_WIN_MAX_HOURS, default=stored(CONF_WIN_MAX_HOURS, DEFAULT_WIN_MAX_HOURS))
        ] = NumberSelector(
            NumberSelectorConfig(
                min=0, max=72, step=0.5, mode=NumberSelectorMode.BOX, unit_of_measurement="h"
            )
        )
        items[
            vol.Required(CONF_BRIEF_DATES_ENABLED, default=stored(CONF_BRIEF_DATES_ENABLED, False))
        ] = BooleanSelector()
        items[
            vol.Optional(
                CONF_BRIEF_DATES,
                description={"suggested_value": stored(CONF_BRIEF_DATES, "")},
            )
        ] = TextSelector(TextSelectorConfig(multiline=True))
        return self.async_show_form(
            step_id="windows",
            data_schema=vol.Schema(items),
            errors=errors,
            description_placeholders=placeholders,
        )

    # -- heating and cooling master switches ------------------------------------

    async def async_step_heat_cool(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        if user_input is not None:
            self._options[CONF_HEAT_ENABLED] = bool(user_input[CONF_HEAT_ENABLED])
            self._options[CONF_COOL_ENABLED] = bool(user_input[CONF_COOL_ENABLED])
            return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HEAT_ENABLED, default=self._options.get(CONF_HEAT_ENABLED, True)
                ): BooleanSelector(),
                vol.Required(
                    CONF_COOL_ENABLED, default=self._options.get(CONF_COOL_ENABLED, True)
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="heat_cool", data_schema=schema)

    # -- seasons --------------------------------------------------------------

    async def async_step_seasons(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        o = self._options
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        pairs = (
            (CONF_HEAT_DATES_ENABLED, CONF_HEAT_DISABLED),
            (CONF_COOL_DATES_ENABLED, CONF_COOL_DISABLED),
        )
        if user_input is not None:
            try:
                heat = engine.parse_date_ranges(user_input.get(CONF_HEAT_DISABLED, ""))
                cool = engine.parse_date_ranges(user_input.get(CONF_COOL_DISABLED, ""))
            except ValueError as err:
                errors["base"] = "invalid_dates"
                placeholders = {"error": str(err)}
            else:
                # The dates are kept while switched off, so they can be switched back on.
                for switch, _dates in pairs:
                    o[switch] = bool(user_input.get(switch, dates_enabled(o, switch)))
                o[CONF_HEAT_DISABLED] = engine.format_date_ranges(heat)
                o[CONF_COOL_DISABLED] = engine.format_date_ranges(cool)
                return await self.async_step_init()

        def suggested(key: str) -> dict[str, Any]:
            if user_input is not None:
                return {"suggested_value": user_input.get(key, "")}
            return {"suggested_value": o.get(key, "")}

        def on(switch: str) -> bool:
            if user_input is not None and switch in user_input:
                return bool(user_input[switch])
            return dates_enabled(o, switch)

        multiline = TextSelector(TextSelectorConfig(multiline=True))
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HEAT_DATES_ENABLED, default=on(CONF_HEAT_DATES_ENABLED)
                ): BooleanSelector(),
                vol.Optional(CONF_HEAT_DISABLED, description=suggested(CONF_HEAT_DISABLED)): multiline,
                vol.Required(
                    CONF_COOL_DATES_ENABLED, default=on(CONF_COOL_DATES_ENABLED)
                ): BooleanSelector(),
                vol.Optional(CONF_COOL_DISABLED, description=suggested(CONF_COOL_DISABLED)): multiline,
            }
        )
        return self.async_show_form(
            step_id="seasons",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )
