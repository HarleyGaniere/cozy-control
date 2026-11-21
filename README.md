# Cozy Control for Home Assistant

Keeps your house comfortable by moving your thermostat's target temperature with the weather outside.

The Nest (and most other) schedules are fixed by time of day. Cozy Control instead looks at the outdoor temperature on a schedule you choose, and sets the thermostat from a table you edit in Home Assistant. For example: 20 outside gives 20 inside, 0 outside gives 22, 30 outside gives 17.

It works with any thermostat that appears as a `climate` entity, and any weather provider or temperature sensor Home Assistant can read (Met.no, NWS, your own sensor in the garden, and so on).

## Features

* **Your own temperature table.** One `outdoor: indoor` pair per line, edited from the integration's settings menu. The target slides smoothly between rows (or steps, if you prefer).
* **Any unit.** The menus follow your Home Assistant unit system, or you can pick Celsius or Fahrenheit. Values are stored in Celsius and converted, so switching units never changes your real temperatures.
* **Any source.** Choose a weather entity (Met.no, NWS, and others) or any temperature sensor as the outdoor reading.
* **Your own schedule.** Choose how often the weather is read and the thermostat is updated, from every minute to once a day. Small changes below a threshold you choose are ignored, so the thermostat is not nudged constantly.
* **Off in mild weather.** Turn the thermostat off while the outdoor temperature is inside a range (for example 19 to 21), and back on when it leaves it.
* **Bedtime temperatures.** A second table that applies every day between a start and end time (for example 20:00 to 05:00, crossing midnight). For example, 17 inside at 20 outside and 18 at 0 outside. Times can be typed as `20:00` or `8:00 PM`, and the menus can show either style (Configure, Source, interval and units, Time format). The thermostat is re-checked exactly when bedtime starts and ends.
* **Away mode.** Track phones with the Home Assistant app (device trackers or people) and switch to a second "away" temperature table while nobody is home. The house counts as home if any watched phone is inside the radius you set around your Home Assistant home location, and as away only when all of them have been outside it for a delay (default 10 minutes), so a quick trip or a bad GPS fix does not trigger it. Readings less accurate than a limit you set are ignored, and if no phone has a usable reading the house counts as home. Coming home takes effect immediately. Every watched phone gets its own switch (for example "Track Alice") so you can turn its location on or off at any time and use as few or as many sources as you like. A presence sensor shows home, away or unknown. Away wins over the bedtime table; the mild-weather off range still applies.
* **Comes back on its own.** After a Home Assistant restart or a power cut, it evaluates again as soon as it loads and again when Home Assistant has finished starting. If the weather or the thermostat is not available yet (other integrations often load later, and a Nest can be offline while the internet is down) it checks again every minute until they are, instead of waiting for the next scheduled update. The pause switch, an open-windows period and your per-phone switches are remembered across restarts. Wait times (for Away mode and for open windows and doors) start counting again after a restart.
* **Several outdoor sources.** Pick more than one outdoor temperature source (weather entities and your own outdoor sensors) and the rules use their weighted average. A second page sets each source's weight, where a bigger number means more influence and 0 ignores it. Sources can use different units, an unavailable source is skipped and the others share its weight, and the outdoor temperature sensor shows which sources and weights are in use. The morning briefing's forecast comes from the first weather entity in the list.
* **Window and door sensors.** Pick any number of window, door, opening or garage door sensors (for example seven windows and a sliding patio door). While any of them is open, the thermostat is turned off; when all are closed it goes back to following the rules and can turn the heating or cooling back on, within a few seconds. A wait time (default 2 minutes) stops a door opened for a moment from switching the heating off. Sensors that are unavailable are ignored. A sensor shows how many are open and which.
* **Safety temperatures.** A last line of defence that looks only at the temperature inside the house. If it reaches your hot limit (for example 30 °C) the air conditioning starts, and if it drops to your cold limit (for example 10 °C) the heating starts, whatever the outdoor weather, the table, Away mode, open windows or doors, the no-heating and no-cooling dates, the heating and cooling switches, or the pause switch say. It holds until the house has recovered by 2 °C, so it does not flip on and off around the limit. It uses the thermostat's own reading, plus any extra room sensors you add (the hottest and coldest reading counts), and reacts as soon as the temperature changes, not at the next scheduled check. It can be switched off, and keeps your numbers when it is. The thermostat's own limits still apply (Nest heats from about 7 °C and cools up to about 35 °C).
* **Indoor temperature sensors.** Make the rules aim at the average of other temperature sensors (a crib sensor, the living room) instead of, or as well as, the thermostat's own reading. Pick them from a dropdown; the thermostat's own reading is used only if you add the thermostat to the list. Each sensor has a weight (a second page appears when more than one is chosen), so a bigger weight means more influence. Add as many time windows as you like, each with its own sensors (an "Add a time window" button adds one at a time), for example the crib sensor from 20:00 to 07:00 and the thermostat the rest of the day. A thermostat steers by its own sensor, so the integration shifts its target by the difference between that reading and your weighted average (never more than a limit you set, and always inside the thermostat's own range). Unavailable sensors are skipped and the others share their weight. This is separate from the Nest app's own temperature sensor feature.
* **Heating and cooling switches.** One menu page turns heating and cooling on or off, together or separately. Turn both off and the thermostat is switched off.
* **Heating and cooling seasons.** Never heat during a date range (for example `06-01 to 08-31`) and never cool during another (for example `11-01 to 03-01`). Ranges repeat every year and can cross New Year. Each list has its own on/off switch that keeps the dates, so you can pause them for a while and switch them back on.
* **Windows and a morning briefing.** A "Windows open" switch turns the thermostat off while the windows are open, and the program resumes when they are shut (or at a time you choose, or after a safety limit). Resuming means following the rules again, so a window or door sensor that still reports open keeps the thermostat off. A morning briefing reads today's forecast and gives advice: a good day to open the windows, or keep them closed because heat or AC will run. It asks a question you can answer yes or no, and it can be limited to certain times of year such as spring and autumn.
* **Safe by design.** A pause switch leaves the thermostat alone, an unavailable weather source or thermostat changes nothing, and a thermostat that refuses a change (for example while in Eco) is reported on a status sensor instead of causing errors.

## Install

### With HACS

1. In HACS, open the menu, choose **Custom repositories**, and add `https://github.com/HarleyGaniere/cozy-control` as type **Integration**.
2. Install **Cozy Control** and restart Home Assistant.

### Manually (also for container installs)

1. Copy the folder `custom_components/cozy_control` into the `custom_components` folder inside your Home Assistant configuration folder. For a container install this is the folder you mount at `/config`.
2. Restart Home Assistant (for a container: restart the container).

### Add it

1. Go to **Settings, Devices & services, Add integration** and search for **Cozy Control**.
2. Choose your outdoor temperature source (a weather entity or a temperature sensor), your thermostat, and how often to update.
3. Open the integration's **Configure** menu to edit the table, bedtime, phones and away temperatures, off range and seasons.

Tip: turn the **Enabled** switch off first. The integration still works out what it would do and shows it on the **Target temperature** and **Status** sensors, but leaves the thermostat alone. Turn it on when you are happy.

## Settings

Open **Configure** on the integration. Choose a section, edit it, then choose **Save and close**.

### Temperature table

One line per pair, as `outdoor: indoor`, in the unit shown in the menu:

```
-20: 23
0: 22
20: 20
30: 17
```

Between rows the target slides smoothly (25 outside gives 18.5 here). Colder or hotter than the table uses the first or last row. Turn off *Slide smoothly between table rows* if you want steps instead.

### Source, interval and units

* **Outdoor temperature source.** A weather entity or a temperature sensor.
* **How often to check and update.** In minutes. The integration reads whatever the weather entity currently shows, so it cannot be fresher than your weather provider. If your provider only updates hourly, checking every 15 minutes simply repeats the same value. A local sensor updates as often as the sensor does.
* **Unit.** Follow Home Assistant, Celsius, or Fahrenheit.
* **Ignore changes smaller than.** The thermostat is only changed when the new target differs by at least this much.
* **Width of the heat/cool range.** For thermostats with a heat/cool range mode (like Nest), the thermostat heats below the target minus half this width and cools above the target plus half.

### Turn off in mild weather

Switch it on and give a From and To outdoor temperature. While the outdoor temperature is within them (inclusive), the thermostat is turned off. Switching it off keeps your From and To values, so you can switch it back on later.

### Disable heating or cooling on dates

One range per line, as `MM-DD to MM-DD`:

```
06-01 to 08-31
```

Use it when the AC breaker is off until a certain date, or you never want heat in summer. A range may cross New Year, for example `11-01 to 02-28`.

## Windows and the morning briefing

Open **Configure, Windows and morning briefing** to set:

* **Pleasant from / up to.** A day whose forecast high is inside this range is a good day to open the windows (default 18 to 23). Below it the advice is to keep the windows closed and heat; above it, to keep them closed and cool.
* **Cold at or below / Hot at or above.** Only change the wording: "it is going to be cold, keep the heat on" or "it is going to be hot, run the AC".
* **After a Yes, resume the program at.** A time of day (default 6:00 PM). The thermostat goes back to following the rules then, but if a window or door sensor still reports open it stays off until they are all closed.
* **Always resume the program after at most.** A safety net (default 12 hours, 0 for never) so the house is not left off if the windows are forgotten open.
* **Use today's forecast.** Needs a weather entity. With a plain temperature sensor the current temperature is used.
* **Only give the briefing on these dates.** For example spring and autumn: `03-15 to 05-31` and `09-15 to 11-15`.

The actions below are on the **Windows open** switch (`switch.<name>_windows_open`). Turning the switch on or off is the same as saying the windows were opened or shut.

* `cozy_control.morning_briefing`: works out the advice, ends any windows-open period, and returns `message` and `question`. Give it a `notify_entity` (for example an Alexa Devices Announce entity) to have the text read aloud.
* `cozy_control.answer` (`yes` or `no`): answers the question from the last briefing for up to two hours. On a good day to open windows, yes turns the thermostat off until the resume time and no keeps it running. On a day to keep windows closed, yes changes nothing and no treats the windows as open.
* `cozy_control.windows_opened` (optional `hours` or `until`) and `cozy_control.windows_closed`.

An automation for a morning routine:

```yaml
triggers:
  - trigger: time
    at: "07:00:00"
actions:
  - action: cozy_control.morning_briefing
    target:
      entity_id: switch.hallway_windows_open
    data:
      notify_entity: notify.kitchen_echo_announce
```

## Entities

For each thermostat the integration creates one device with:

* `sensor.<name>_outdoor_temperature`: the outdoor temperature in use.
* `sensor.<name>_target_temperature`: the indoor target it worked out (the middle of the range when a heat/cool range is used).
* `sensor.<name>_status`: why the thermostat is set the way it is (following the table, off because it is mild, heating disabled, paused, source unavailable, and so on).
* `switch.<name>_enabled`: pause and resume. The state survives restarts.
* `switch.<name>_windows_open`: on while the windows are open and the thermostat is off. The state survives restarts, and its `resumes_at` attribute shows when it ends.
* `button.<name>_update_now`: re-check right now.

## How the thermostat is controlled

When both heating and cooling are allowed and the thermostat supports a heat/cool range (`heat_cool`), the integration uses that range around the target. Otherwise it chooses heat when it is colder outside than the target and cool when it is warmer. If only one of them is allowed, that one is used. If neither is allowed, or the outdoor temperature is in the off range, the thermostat is turned off. Targets are limited to the thermostat's own minimum and maximum and rounded to its step.

## Not included yet

* Ready-made Alexa and Google Home setup. The pieces above work with any voice assistant, but the wiring (routines, a Matter bridge, spoken replies) is not written up yet.
* Noticing a manual change on the thermostat and backing off. For now, use the pause switch.

## Development

```bash
python -m venv venv && . venv/bin/activate
pip install pytest-homeassistant-custom-component ruff
pytest
```

The comfort logic lives in `custom_components/cozy_control/engine.py` and has no Home Assistant dependency, so it is easy to test and reuse.

## License

GPL-3.0, see `LICENSE`.
