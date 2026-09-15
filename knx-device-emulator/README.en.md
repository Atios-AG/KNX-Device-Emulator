*English · [Русский](README.md) · [Deutsch](README.de.md)*

# KNX Device Emulator

A simulator of virtual KNX devices. It emulates an arbitrary number of devices
that behave on the bus like hardware ones: they react to commands
(`GroupValueWrite`), answer polls (`GroupValueRead` → `Response`) and broadcast
their status on their own whenever the state changes. It connects to the bus
over **KNXnet/IP** (tunneling to your IP device, or routing).

On top of that there is a **control interface** — a single channel through
which a device state can be changed "as if locally" (like a button press on a
panel): the device changes its state and reports the new status to the bus
itself.

## Installation and start-up

```bash
pip install -r requirements.txt
cp config.example.ini config.ini      # edit it for your own environment
python main.py --config config.ini
```

## Architecture

```
config.ini ─▶ ConfigLoader ─▶ DeviceManager ◀─ DeviceRegistry ◀─ devices/*.py
                                   │  ▲
                  ControlInterface ┘  │  routes (GA→DataPoint)
                  (REST/CLI)          ▼
                                  BusAdapter ──KNXnet/IP──▶ KNX bus
```

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Start-up | `main.py` | wiring of the components, signals |
| Config | `core/config_loader.py` | ini parsing/validation |
| Plugins | `core/registry.py` | auto-discovery of the devices in `devices/` |
| Runtime | `core/device_manager.py` | telegram routing GA→device |
| Bus | `core/bus_adapter.py` (`core/bus.py`) | bridge to xknx; a fake in the tests |
| Contract | `core/device.py` | `BaseDevice`, `@local_command` |
| Data points | `core/datapoint.py` | Action/Status (group objects) |
| Codecs | `core/dpt.py`, `core/address.py` | DPT and Group Address |
| Control | `core/control/` | `ControlInterface` + transports |

Three sources of a state change, all of them lead to a status broadcast on the
bus:
1. **from the bus** — a `Write` at the Action address → `on_action()`;
2. **polling** — a `Read` at the Status address → `Response`;
3. **locally** — a command via `ControlInterface` → `@local_command`.

## How to add a device (a single file)

Create `devices/my_device.py` with a class that subclasses `BaseDevice`:

```python
from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL

class MyDevice(BaseDevice):
    TYPE = "my_device"                 # the link to the config: type = my_device

    def setup(self):
        self._state = False
        self.action = self.add(
            ActionPoint("action", self.config.get_ga("Action"), DPT_BOOL, self.on_action))
        self.status = self.add(
            StatusPoint("on", self.config.get_ga("Status"), DPT_BOOL, lambda: self._state))

    def on_action(self, value):        # a command from the bus
        self._state = value
        self.publish(self.status)

    @local_command("toggle")           # a command from the panel — handled HERE
    def cmd_toggle(self):
        self._state = not self._state
        self.publish(self.status)
        return self.state_snapshot()
```

The registry picks it up automatically. Add a section with `type = my_device`
to `config.ini`.

## Thermostat / air conditioner: the modes

The target mode arrives only at `ActionMode` (DPT 20.105), the current mode
(`StatusMode`) mirrors it:

| Value on the bus | Mode | Behaviour |
|---|---|---|
| 1 | `off`  | the device is switched off (`StatusOnOff` = 0) |
| 2 | `heat` | heating up to `Setpoint` |
| 3 | `cool` | cooling down to `Setpoint` |
| 4 | `auto` | the device chooses heating or cooling itself |

`On/Off` and the mode are equivalent: `mode = off` switches the device off,
while `On/Off = on` restores the last active mode (`auto` included).

**AUTO** compares the current temperature with the target one: below
`Setpoint - AutoHysteresis` it heats, above `Setpoint + AutoHysteresis` it
cools, inside the band it idles; a heating/cooling that has started runs up to
`Setpoint` (hysteresis against chattering). It is exactly `auto` that goes on
the bus meanwhile, and the chosen direction is visible in the panel state as
`auto_action`.

**AUTO is available only if the seasonal mode is not activated** — that is, the
device section has no `StatusSeason`/`Season`. With a season set, the direction
is already fixed (summer → only `cool`, winter → only `heat`), so an `auto`
command from the bus or from the panel is ignored (with a log entry).

## Garage door: travel time and status flavours

Type `garage_door`. The only control object is the `Action` bit (DPT 1.008):
`0` = open (Up), `1` = close (Down); `Inverted = True` swaps them. Like a real
drive, the door travels for `TravelSec` seconds from one end position to the
other. An opposite command while the door is moving reverses it from the
current virtual position — the rest of the travel takes a proportional time.
A command in the same direction (or "open" for a door that is already open)
is ignored without any telegram, only with a line in the log.

The status can be reported in three ways, all of them **optional and
independent**: a flavour is active when its group address is set in the
config (any combination, even all three at once).

| Key | DPT | Behaviour |
|---|---|---|
| `Status` | 1.008 | one bit that follows the command semantics: `1` = closed (with `Inverted` — `1` = open). Updated only at the end positions |
| `StatusPosition` | 5.001 | `0 %` = closed, `100 %` = open. Updated only at the end positions |
| `SensorOpened` / `SensorClosed` | 1.002 | two end-position sensors, `1` = the door rests at that end |

The sensor sequence when opening from the closed position:

| Moment | `SensorOpened` | `SensorClosed` |
|---|---|---|
| closed | 0 | 1 |
| started opening | 0 | 0 (telegram `SensorClosed` → 0) |
| travelling | 0 | 0 |
| fully open | 1 (telegram `SensorOpened` → 1) | 0 |

Panel commands: `open`, `close` (the same as the bus command) and `stop` —
a halt half-way: both sensors stay `0`, the bit and the percentage keep
reporting the last end position reached. The next `open`/`close` continues
from the halt point.

```ini
[garage0]
type           = garage_door
Action         = 1/7/1     ; command (DPT 1.008)
Status         = 2/7/1     ; bit (optional)
StatusPosition = 2/7/2     ; percentage (optional)
SensorOpened   = 2/7/3     ; "open" sensor (optional)
SensorClosed   = 2/7/4     ; "closed" sensor (optional)
TravelSec      = 15        ; full travel time, s (10 by default)
State          = closed    ; initial state: closed | open
Inverted       = False
```

## Control interface (REST)

```
GET  /devices                      # the list of devices + their state
GET  /devices/{name}               # state + available commands
POST /devices/{name}/commands      # {"command": "set", "args": {"on": true}}
```

Example:
```bash
curl -X POST localhost:8080/devices/outlet0/commands \
     -H 'Content-Type: application/json' \
     -d '{"command":"toggle"}'
```

### CLI (transport = cli)

A REPL in the console with **TAB completion** (based on `prompt_toolkit`): TAB
shows the options available at the current level with a description on the
right — devices → the device's commands → `key=` arguments and value hints.

```
knx> <device> <command> [key=value ...]      # the command format
knx> outlet0 toggle
knx> thermostat_room set_mode mode=heat
knx> thermostat_room set_mode mode=auto        # it will choose heating/cooling itself
knx> thermostat_room set_onoff on=true
knx> list | describe <dev> | help | quit      # built-ins
```

If stdin is not a TTY (input from a pipe), the completion is disabled and plain
line input is used.

## Tests

```bash
pytest                 # all the logic is tested on FakeBusAdapter, without a network
```
