# KNX Device Emulator

A simulator of virtual KNX devices. You can run as many devices as you like, and
on the bus they behave like real hardware: they react to commands
(`GroupValueWrite`), answer when polled (`GroupValueRead` → `Response`) and send
out their status on their own whenever their state changes. The emulator talks
to the bus over **KNXnet/IP** — tunneling to your IP device, or routing.

There is also a **control interface**: one channel for changing a device's state
"locally", as if someone had pressed a button on its panel. The device changes
its state and reports the new status to the bus itself.

## Install and run

```bash
pip install -r requirements.txt
cp config.example.ini config.ini      # edit it to match your setup
python main.py --config config.ini
```

Options: `--log-level DEBUG` gives you a detailed log; `--shutdown-timeout N` is
how many seconds to wait for a clean shutdown after Ctrl+C (3 by default; a
second Ctrl+C quits right away).

## Architecture

```
config.ini ─▶ ConfigLoader ─▶ DeviceManager ◀─ DeviceRegistry ◀─ devices/*.py
                                   │  ▲
                  ControlInterface ┘  │  routes (GA→DataPoint)
                  (REST/CLI)          ▼
                                  BusAdapter ──KNXnet/IP──▶ KNX bus
```

| Layer | Module | What it does |
|-------|--------|--------------|
| Start-up | `main.py` | wires the components together, handles signals |
| Config | `core/config_loader.py` | parses and validates the ini file |
| Plugins | `core/registry.py` | finds the devices in `devices/` automatically |
| Runtime | `core/device_manager.py` | routes telegrams from a group address to its device |
| Bus | `core/bus_adapter.py` (`core/bus.py`) | the bridge to xknx; a fake one in the tests |
| Contract | `core/device.py` | `BaseDevice`, `@local_command` |
| Data points | `core/datapoint.py` | Action / Status (group objects) |
| Codecs | `core/dpt.py`, `core/address.py` | DPT and group address |
| Control | `core/control/` | `ControlInterface` and its transports |

A device responds to three things:
1. **the bus** — a `Write` to an Action address calls `on_action()`;
2. **polling** — a `Read` on a Status address gets a `Response`;
3. **local control** — a command through `ControlInterface` runs a `@local_command`.

The first and the third change the device's state, and the device then reports
the new status to the bus.

## Adding a device (one file)

Create `devices/my_device.py` with a class that subclasses `BaseDevice`:

```python
from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL

class MyDevice(BaseDevice):
    TYPE = "my_device"                 # ties it to the config: type = my_device

    def setup(self):
        self._state = False
        self.action = self.add(
            ActionPoint("action", self.config.get_ga("Action"), DPT_BOOL, self.on_action))
        self.status = self.add(
            StatusPoint("on", self.config.get_ga("Status"), DPT_BOOL, lambda: self._state))

    def on_action(self, value):        # a command from the bus
        self._state = value
        self.publish(self.status)

    @local_command("toggle")           # a command from the panel — handled right here
    def cmd_toggle(self):
        self._state = not self._state
        self.publish(self.status)
        return self.state_snapshot()
```

The registry picks it up on its own. Then add a section to `config.ini`: `type`
ties the section to the plugin, and the rest are whatever keys the device reads
in `setup()` — here, the group addresses:

```ini
[lamp0]
type   = my_device
Action = 1/1/1        ; commands arrive here (GroupValueWrite)
Status = 2/1/1        ; the status is read from here and sent out here
```

You don't configure the kind of telegram — the point class decides it: an
`ActionPoint` takes a write and calls your handler, a `StatusPoint` answers a
read and sends the value on `publish()` and at start-up.

### Your own data type (DPT)

The value type is set by the DPT codec you pass to the point. The core
(`core/dpt.py`) comes with:

| Codec | DPT | Value |
|---|---|---|
| `DPT_BOOL` | 1.001 | one bit; works for any one-bit type (1.002, 1.008, 1.010 …) |
| `DPT_SCALING` | 5.001 | 0..100 % |
| `DPT_UCOUNT` | 5.010 | one byte, 0..255 |
| `DPT_TEMPERATURE` | 9.001 | °C |
| `DPT_AIR_QUALITY_PPM` | 9.008 | ppm |
| `DPT_CONCENTRATION_UGM3` | 9.030 | µg/m³ |

If the one you need isn't there, declare it in the same device file — no need to
touch the core:

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

DPT_PULSES = DPTPulses()               # pass it to a point instead of DPT_BOOL
```

`payload_kind` says what the payload looks like: `"binary"` is a value of up to
6 bits — `encode` returns an `int` and `decode` gets an `int`; `"array"` is one
or more bytes — `encode` returns `bytes` and `decode` gets `bytes`. That's how
20.105 and 1.100 are declared in `devices/thermostat.py`. If several devices
need the same type, put it in `core/dpt.py` instead.

## Devices

| `type` | Objects on the bus | Panel commands | Notes |
|---|---|---|---|
| `outlet` | `Action` / `Status` (DPT 1.001) | `toggle`, `set on=` | `Inverted` flips the state relative to the bus |
| `dimmer` | `Action` / `Status` (1.001), `ActionDim` / `StatusDim` (5.001) | `toggle`, `set_level level=` | |
| `thermostat` | setpoint and current temperature (9.001), mode (20.105), On/Off (1.001), season (1.100) | `set_onoff on=`, `set_mode mode=`, `set_setpoint value=`, `set_current value=`, `set_season season=` | see the section below |
| `air_conditioner` | everything the `thermostat` has, plus a fan: `ActionFan` / `StatusFan` (5.001, 0..100 %) | the same, plus `set_fan level=` | |
| `fan` | `ActionFan` / `StatusFan` — the speed step as one byte (5.010) | `set_speed speed=`, `off` | `Speeds` is the number of steps, 1..4; a step above the last one is dropped |
| `fan_relay` | `ActionSpeedN` / `StatusSpeedN` — one relay per step (1.001) | `set_speed speed=`, `off` | checks how the actuator switches: all windings off first, then the right one on; violations are logged as errors |
| `air_quality_sensor` | statuses only: `StatusAQI` (5.010), `StatusCO2` / `StatusTVOC` / `StatusCH2O` (9.008), `StatusPM1` / `StatusPM2_5` / `StatusPM10` (9.030) | `<sensor> set=`, e.g. `co2 set=400` | a sensor exists if its address is set; `CycleSec` is the period of the cyclic broadcast |
| `garage_door` | `Action` (1.008) or the pair `ActionOpen` / `ActionClose`; statuses: a bit, a percentage, two sensors | `open`, `close`, `stop` | see the section below |
| `shutter` | `Movement` (1.008), `Stop` (1.010), `TargetPosition` / `CurrentPosition` (5.001), `StatusMovement` (1.008) | `up`, `down`, `stop`, `position percent=` | `0 %` = open, `100 %` = closed; the position is reported once the drive has stopped |

Every config key, with an example section for each type, is in
`config.example.ini`; how a device behaves is described at the top of its file
(`devices/*.py`).

## Thermostat / air conditioner: modes

The target mode only comes in on `ActionMode` (DPT 20.105); the current mode
(`StatusMode`) mirrors it:

| Value on the bus | Mode | What happens |
|---|---|---|
| 1 | `off`  | the device is off (`StatusOnOff` = 0) |
| 2 | `heat` | heats up to `Setpoint` |
| 3 | `cool` | cools down to `Setpoint` |
| 4 | `auto` | the device picks heating or cooling itself |

`On/Off` and the mode go hand in hand: `mode = off` switches the device off, and
`On/Off = on` brings back the last active mode (including `auto`).

In **AUTO** the device compares the current temperature with the setpoint: below
`Setpoint - AutoHysteresis` it heats, above `Setpoint + AutoHysteresis` it cools,
and in between it idles. Once it has started heating or cooling it keeps going
until `Setpoint`, so it doesn't flip back and forth. The bus still sees plain
`auto`; the direction the device picked shows up in the panel state as
`auto_action`.

**AUTO only works when the seasonal mode is off** — that is, when the device
section has no `StatusSeason`. With a season set, the direction is already fixed
(summer → `cool` only, winter → `heat` only), so an `auto` command from the bus
or from the panel is ignored and a warning goes to the log.

## Garage door: travel time and status variants

The type is `garage_door`. By default it is controlled by one bit, `Action`
(DPT 1.008): `0` = open (Up), `1` = close (Down); `Inverted = True` swaps them
(impulse and relay drives are covered under "Drive variants" below). Like a real
drive, the door takes `TravelSec` seconds to get from one end to the other. A
command the other way while it is moving turns the door around from wherever it
is, and the rest of the trip takes a proportional time. A command in the same
direction (or "open" when the door is already open) is ignored: no telegrams,
just a line in the log.

There are three ways to report the status, all of them **optional and
independent** — whichever has its group address in the config is active (all
three at once is fine):

| Key | DPT | Behaviour |
|---|---|---|
| `Status` | 1.008 | one bit with the same meaning as the command: `1` = closed (with `Inverted`, `1` = open). Updated only at the end positions |
| `StatusPosition` | 5.001 | `0 %` = closed, `100 %` = open (`InvertedPosition = True` flips the scale). Updated only at the end positions |
| `SensorOpened` / `SensorClosed` | 1.002 | two limit sensors, `1` = the door is at that end (`InvertedSensorOpened` / `InvertedSensorClosed = True`: `0` at the end, like a normally-closed contact) |

What the sensors do while the door opens from the closed position:

| Moment | `SensorOpened` | `SensorClosed` |
|---|---|---|
| closed | 0 | 1 |
| starts opening | 0 | 0 (telegram `SensorClosed` → 0) |
| travelling | 0 | 0 |
| fully open | 1 (telegram `SensorOpened` → 1) | 0 |

Panel commands: `open` and `close` (same as the bus command) and `stop`, which
halts the door half-way: both sensors stay at `0`, while the bit and the
percentage keep showing the last end position the door reached. The next
`open` / `close` carries on from where it stopped.

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
InvertedSensorOpened = False   ; True: SensorOpened = 0 when the door is fully open
InvertedSensorClosed = False   ; True: SensorClosed = 0 when the door is fully closed
Impulse        = False     ; True: a telegram while the door is moving stops the drive
PushButton     = False     ; True: Action is the drive's push button, the bit value doesn't matter
```

### Drive variants

By default the emulator behaves like a motor: the bit sets the direction. For
other drives:

| Setting | Behaviour |
|---|---|
| `Impulse = True` | a drive with a stop state: a telegram while the door is moving stops it where it is (like `stop`); a telegram while it is standing moves it the way the bit says |
| `PushButton = True` | `Action` is the drive's push button and the bit value doesn't matter. At an end position a press moves the door away from that end; after a half-way stop it goes back the other way. A press while the door is moving turns it around — or stops it if `Impulse = True` is set as well. That gives the "open → close" and "open → stop → close → stop" cycles |
| `ActionOpen` + `ActionClose` | two pulsed channels instead of `Action`: any telegram on `ActionOpen` opens, any telegram on `ActionClose` closes, whatever the value. You have to set both addresses; `Action` is not used then, and `Impulse` / `PushButton` have no effect on the two channels. Otherwise the same rules apply as for the bit: a command the other way turns the door around, a repeat is ignored |

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
GET  /devices                      # all devices with their state
GET  /devices/{name}               # state and available commands
POST /devices/{name}/commands      # {"command": "set", "args": {"on": true}}
```

Example:
```bash
curl -X POST localhost:8080/devices/outlet0/commands \
     -H 'Content-Type: application/json' \
     -d '{"command":"toggle"}'
```

### CLI (transport = cli)

A console REPL with **TAB completion** (built on `prompt_toolkit`): TAB shows
what's available at the current level, with a description on the right —
devices → that device's commands → `key=` arguments and value hints.

```
knx> <device> <command> [key=value ...]      # command format
knx> outlet0 toggle
knx> thermostat_room set_mode mode=heat
knx> thermostat_room set_mode mode=auto        # picks heating or cooling itself; needs a section without StatusSeason
knx> thermostat_room set_onoff on=true
knx> list | describe <dev> | help | quit      # built-ins
```

If stdin isn't a TTY (the input comes from a pipe), completion is off and plain
line-by-line input is used.

## Tests

```bash
pytest                 # runs without a network: the bus is replaced by a stand-in
```
