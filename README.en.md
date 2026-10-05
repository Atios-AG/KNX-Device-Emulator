*English · [Русский](README.md)*

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

Start-up options: `--log-level DEBUG` — a detailed log; `--shutdown-timeout N` —
how many seconds to wait for a graceful shutdown after Ctrl+C (3 by default; a
second Ctrl+C terminates at once).

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

The registry picks it up automatically. Add a section to `config.ini`: `type`
links it to the plugin, the other keys are the ones the device reads in
`setup()` (here these are the group addresses):

```ini
[lamp0]
type   = my_device
Action = 1/1/1        ; the command arrives here (GroupValueWrite)
Status = 2/1/1        ; the status is read from and broadcast to here
```

The kind of telegram is set by the class of the point and needs no
configuration: an `ActionPoint` accepts a write and calls the handler, a
`StatusPoint` answers a read and broadcasts the value on `publish()` and at
start-up.

### Your own data type (DPT)

The type of a value is set by the DPT codec that is passed to the point. The
core (`core/dpt.py`) has:

| Codec | DPT | Value |
|---|---|---|
| `DPT_BOOL` | 1.001 | a bit; fits any one-bit type (1.002, 1.008, 1.010 …) |
| `DPT_SCALING` | 5.001 | 0..100 % |
| `DPT_UCOUNT` | 5.010 | a byte 0..255 |
| `DPT_TEMPERATURE` | 9.001 | °C |
| `DPT_AIR_QUALITY_PPM` | 9.008 | ppm |
| `DPT_CONCENTRATION_UGM3` | 9.030 | µg/m³ |

If the one you need is missing, declare it in the same device file — the core
stays untouched:

```python
from core.dpt import DPT
from core.exceptions import DPTError

class DPTPulses(DPT):
    main, sub = 7, 1                   # DPT 7.001: two unsigned bytes
    payload_kind = "array"

    def encode(self, value) -> bytes:  # Python value -> payload for the bus
        v = int(value)
        if not 0 <= v <= 0xFFFF:
            raise DPTError(f"7.001 out of range 0..65535: {v}")
        return bytes([v >> 8, v & 0xFF])

    def decode(self, raw) -> int:      # payload from the bus -> Python value
        if len(raw) < 2:
            raise DPTError("7.001: 2 bytes expected")
        return (raw[0] << 8) | raw[1]

DPT_PULSES = DPTPulses()               # passed to a point instead of DPT_BOOL
```

`payload_kind` sets the form of the payload: `"binary"` — a value of up to
6 bits, `encode` returns an `int` and `decode` gets an `int`; `"array"` — one
or several bytes, `encode` returns `bytes` and `decode` gets `bytes`. This is
how 20.105 and 1.100 are declared in `devices/thermostat.py`. A type that
several devices need is better placed in `core/dpt.py`.

## Devices

| `type` | Objects on the bus | Panel commands | Note |
|---|---|---|---|
| `outlet` | `Action` / `Status` (DPT 1.001) | `toggle`, `set on=` | `Inverted` inverts the state relative to the bus |
| `dimmer` | `Action` / `Status` (1.001), `ActionDim` / `StatusDim` (5.001) | `toggle`, `set_level level=` | |
| `thermostat` | setpoint and current temperature (9.001), mode (20.105), On/Off (1.001), season (1.100) | `set_onoff on=`, `set_mode mode=`, `set_setpoint value=`, `set_current value=`, `set_season season=` | see the section below |
| `air_conditioner` | everything of `thermostat` and the fan `ActionFan` / `StatusFan` (5.001, 0..100 %) | the same and `set_fan level=` | |
| `fan` | `ActionFan` / `StatusFan` — the step number in one byte (5.010) | `set_speed speed=`, `off` | `Speeds` — the number of steps, 1..4; a step above the last one is discarded |
| `fan_relay` | `ActionSpeedN` / `StatusSpeedN` — a relay per step (1.001) | `set_speed speed=`, `off` | verifies the actuator's algorithm: switch all the windings off first, then the needed one on; violations go to the log as errors |
| `air_quality_sensor` | statuses only: `StatusAQI` (5.010), `StatusCO2` / `StatusTVOC` / `StatusCH2O` (9.008), `StatusPM1` / `StatusPM2_5` / `StatusPM10` (9.030) | `<sensor> set=`, for example `co2 set=400` | a sensor is present when its address is set; `CycleSec` — the cyclic broadcast period |
| `garage_door` | `Action` (1.008) or the pair `ActionOpen` / `ActionClose`; statuses — a bit, a percentage, two sensors | `open`, `close`, `stop` | see the section below |
| `shutter` | `Movement` (1.008), `Stop` (1.010), `TargetPosition` / `CurrentPosition` (5.001), `StatusMovement` (1.008) | `up`, `down`, `stop`, `position percent=` | `0 %` = open, `100 %` = closed; the position is reported when the drive comes to rest |

All the configuration keys, with an example section for every type, are in
`config.example.ini`; the behaviour of a device is described at the top of its
file (`devices/*.py`).

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

Type `garage_door`. By default the control object is the `Action` bit
(DPT 1.008): `0` = open (Up), `1` = close (Down); `Inverted = True` swaps them
(impulse and relay drives are in the "Drive variants" subsection). Like a real
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
| `StatusPosition` | 5.001 | `0 %` = closed, `100 %` = open (`InvertedPosition = True` flips the scale). Updated only at the end positions |
| `SensorOpened` / `SensorClosed` | 1.002 | two end-position sensors, `1` = the door rests at that end (`InvertedSensorOpened` / `InvertedSensorClosed = True`: `0` at the end, like a normally-closed contact) |

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
Inverted       = False     ; True: command 1 = open, bit status 1 = open
InvertedPosition     = False   ; True: 0 % = open, 100 % = closed
InvertedSensorOpened = False   ; True: SensorOpened = 0 while the door rests fully open
InvertedSensorClosed = False   ; True: SensorClosed = 0 while the door rests fully closed
Impulse        = False     ; True: a telegram while moving halts the drive
PushButton     = False     ; True: Action is the push button of the drive, the bit value does not matter
```

### Drive variants

By default a motor is emulated: the bit sets the direction. For other drives:

| Setting | Behaviour |
|---|---|
| `Impulse = True` | a drive with a stop state: a telegram while the door is moving halts it where it is (like `stop`), a telegram while it stands moves it as the bit asks |
| `PushButton = True` | `Action` is the push button of the drive, the bit value does not matter. At an end position a press moves the door away from that end, after a half-way halt — in the opposite direction. A press while moving reverses the door, and together with `Impulse = True` halts it: the "open → close" and "open → stop → close → stop" cycles |
| `ActionOpen` + `ActionClose` | two pulsed channels instead of `Action`: any telegram on `ActionOpen` opens, on `ActionClose` closes, the value does not matter. The addresses are set only as a pair, `Action` is not used then, and `Impulse` / `PushButton` do not affect the two channels. After that the same rules as for the bit apply: an opposite command reverses, a repeat is ignored |

```ini
[garage_relays]
type         = garage_door
ActionOpen   = 1/7/8       ; "open" pulse
ActionClose  = 1/7/9       ; "close" pulse
SensorOpened = 2/7/3
SensorClosed = 2/7/4
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
