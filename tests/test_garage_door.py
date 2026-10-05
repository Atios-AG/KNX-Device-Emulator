"""Garage door: one-bit command (DPT 1.008) + three optional status flavours.

The drive travels for TravelSec between the end positions; the bit and the
percentage report end positions only, the two limit-switch sensors drop to 0
as soon as the door leaves an end and rise to 1 when it reaches the other.
"""

import asyncio
import logging

import pytest

from core.address import GroupAddress
from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.exceptions import InvalidValueError, MissingOptionError
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter

ACTION, STATUS, POSITION, OPENED, CLOSED = "1/7/1", "2/7/1", "2/7/2", "2/7/3", "2/7/4"
ACTION_OPEN, ACTION_CLOSE = "1/7/8", "1/7/9"

_BASE = {
    "type": "garage_door",
    "Action": ACTION,
    "Status": STATUS,
    "StatusPosition": POSITION,
    "SensorOpened": OPENED,
    "SensorClosed": CLOSED,
    "TravelSec": "10",
}


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, sec):
        self.t += sec


def _setup(extra=None, remove=()):
    data = dict(_BASE)
    if extra:
        data.update(extra)
    for key in remove:
        data.pop(key, None)
    cfg = DeviceConfig("garage0", data)
    reg = DeviceRegistry(); reg.discover("devices")
    bus = FakeBusAdapter()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[DeviceEntry("garage0", "garage_door", cfg)]))
    dev = mgr.get_device("garage0")
    dev._clock = FakeClock()
    return dev, bus, ControlInterface(mgr)


def _writes(bus):
    """Telegrams as (ga string, value) pairs, in the order they were sent."""
    return [(str(ga), value) for ga, value in bus.writes]


def _infos(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]


# --- configuration -----------------------------------------------------------

def test_registered_as_type():
    reg = DeviceRegistry(); reg.discover("devices")
    assert "garage_door" in reg.types


def test_initial_state_closed_by_default():
    dev, bus, _ = _setup()
    assert dev.state_snapshot() == {
        "state": "closed", "position": 0.0,
        "status": True, "status_position": 0.0,
        "sensor_opened": False, "sensor_closed": True,
    }


def test_initial_state_open_from_config():
    dev, bus, _ = _setup({"State": "Open"})
    assert dev.state_snapshot() == {
        "state": "open", "position": 100.0,
        "status": False, "status_position": 100.0,
        "sensor_opened": True, "sensor_closed": False,
    }


def test_initial_status_broadcast_at_startup():
    dev, bus, _ = _setup()
    dev.publish_all_status()
    assert _writes(bus) == [
        (STATUS, True), (POSITION, 0.0), (OPENED, False), (CLOSED, True),
    ]


def test_default_travel_time():
    dev, _, _ = _setup(remove=("TravelSec",))
    assert dev._travel == 10.0


def test_action_is_required():
    with pytest.raises(MissingOptionError):
        _setup(remove=("Action",))


@pytest.mark.parametrize("bad", ["0", "-3", "fast"])
def test_travel_time_must_be_positive_number(bad):
    with pytest.raises(InvalidValueError):
        _setup({"TravelSec": bad})


def test_initial_state_must_be_open_or_closed():
    with pytest.raises(InvalidValueError):
        _setup({"State": "ajar"})


# --- optional status flavours ------------------------------------------------

def test_statuses_are_optional_and_independent():
    dev, bus, _ = _setup(remove=("Status", "StatusPosition", "SensorOpened", "SensorClosed"))
    assert dev.state_snapshot() == {"state": "closed", "position": 0.0}
    dev.publish_all_status()
    bus.inject(ACTION, "write", 0)
    dev._clock.advance(10)
    dev._arrive()
    assert bus.writes == []  # nothing to report with, still fully functional
    assert dev.state == "open"


def test_only_bit_status():
    dev, bus, _ = _setup(remove=("StatusPosition", "SensorOpened", "SensorClosed"))
    bus.inject(ACTION, "write", 0)
    assert bus.writes == []
    dev._clock.advance(10)
    dev._arrive()
    assert _writes(bus) == [(STATUS, False)]


def test_only_sensors():
    dev, bus, _ = _setup(remove=("Status", "StatusPosition"))
    bus.inject(ACTION, "write", 0)
    assert _writes(bus) == [(CLOSED, False)]
    dev._clock.advance(10)
    dev._arrive()
    assert _writes(bus) == [(CLOSED, False), (OPENED, True)]


# --- opening / closing sequence ----------------------------------------------

def test_open_from_closed_sequence():
    dev, bus, _ = _setup()
    bus.inject(ACTION, "write", 0)  # DPT 1.008: 0 = up = open
    # the door left the closed end: only the closed sensor drops to 0
    assert _writes(bus) == [(CLOSED, False)]
    assert dev.state == "opening"
    assert dev._arrival_due - dev._clock() == 10.0
    # half-way: bit and % still report the closed end, sensors both 0
    dev._clock.advance(5)
    assert dev.state_snapshot() == {
        "state": "opening", "position": 50.0,
        "status": True, "status_position": 0.0,
        "sensor_opened": False, "sensor_closed": False,
    }
    assert _writes(bus) == [(CLOSED, False)]
    # arrival: bit, % and the opened sensor go out
    dev._clock.advance(5)
    dev._arrive()
    assert _writes(bus) == [
        (CLOSED, False), (STATUS, False), (POSITION, 100.0), (OPENED, True),
    ]
    assert dev.state_snapshot() == {
        "state": "open", "position": 100.0,
        "status": False, "status_position": 100.0,
        "sensor_opened": True, "sensor_closed": False,
    }


def test_close_from_open_sequence():
    dev, bus, _ = _setup({"State": "open"})
    bus.inject(ACTION, "write", 1)  # 1 = down = close
    assert _writes(bus) == [(OPENED, False)]
    assert dev.state == "closing"
    dev._clock.advance(10)
    dev._arrive()
    assert _writes(bus) == [
        (OPENED, False), (STATUS, True), (POSITION, 0.0), (CLOSED, True),
    ]
    assert dev.state == "closed"


def test_read_while_moving_answers_last_end_position():
    dev, bus, _ = _setup()
    bus.inject(ACTION, "write", 0)
    dev._clock.advance(5)
    bus.inject(STATUS, "read", None)
    bus.inject(POSITION, "read", None)
    bus.inject(OPENED, "read", None)
    bus.inject(CLOSED, "read", None)
    assert [(str(ga), v) for ga, v in bus.responses] == [
        (STATUS, True), (POSITION, 0.0), (OPENED, False), (CLOSED, False),
    ]


# --- ignored commands --------------------------------------------------------

def test_open_when_already_open_is_ignored(caplog):
    dev, bus, _ = _setup({"State": "open"})
    with caplog.at_level(logging.INFO):
        bus.inject(ACTION, "write", 0)
    assert bus.writes == []
    assert dev.state == "open"
    assert any("ignored" in m and "already open" in m for m in _infos(caplog))


def test_close_when_already_closed_is_ignored(caplog):
    dev, bus, _ = _setup()
    with caplog.at_level(logging.INFO):
        bus.inject(ACTION, "write", 1)
    assert bus.writes == []
    assert dev.state == "closed"
    assert any("ignored" in m and "already closed" in m for m in _infos(caplog))


def test_repeated_command_while_moving_is_ignored(caplog):
    dev, bus, _ = _setup()
    bus.inject(ACTION, "write", 0)
    dev._clock.advance(3)
    with caplog.at_level(logging.INFO):
        bus.inject(ACTION, "write", 0)
    assert _writes(bus) == [(CLOSED, False)]
    assert any("ignored" in m and "already opening" in m for m in _infos(caplog))
    # the travel was not restarted
    assert dev._arrival_due - dev._clock() == 7.0


# --- reversing and stopping --------------------------------------------------

def test_reverse_while_moving_continues_from_current_position():
    dev, bus, _ = _setup()
    bus.inject(ACTION, "write", 0)
    dev._clock.advance(4)  # 40 % open
    bus.inject(ACTION, "write", 1)
    assert dev.state == "closing"
    assert dev.state_snapshot()["position"] == 40.0
    # closing 40 % takes 4 s; sensors are already 0 — no extra telegrams
    assert dev._arrival_due - dev._clock() == pytest.approx(4.0)
    assert _writes(bus) == [(CLOSED, False)]
    dev._clock.advance(2)
    assert dev.state_snapshot()["position"] == 20.0
    dev._clock.advance(2)
    dev._arrive()
    assert dev.state == "closed"
    assert _writes(bus) == [
        (CLOSED, False), (STATUS, True), (POSITION, 0.0), (CLOSED, True),
    ]


def test_stop_halts_half_way_without_telegrams(caplog):
    dev, bus, ctl = _setup()
    bus.inject(ACTION, "write", 0)
    dev._clock.advance(4)
    with caplog.at_level(logging.INFO):
        res = ctl.execute(Command("garage0", "stop"))
    assert res.ok
    assert res.state == {
        "state": "stopped", "position": 40.0,
        "status": True, "status_position": 0.0,
        "sensor_opened": False, "sensor_closed": False,
    }
    assert _writes(bus) == [(CLOSED, False)]
    assert any("stopped at 40 %" in m for m in _infos(caplog))
    # time passes — the door stays where it is
    dev._clock.advance(30)
    assert dev.state_snapshot()["position"] == 40.0


def test_resume_after_stop_takes_the_remaining_time():
    dev, bus, ctl = _setup()
    bus.inject(ACTION, "write", 0)
    dev._clock.advance(4)
    ctl.execute(Command("garage0", "stop"))
    bus.inject(ACTION, "write", 0)  # continue opening from 40 %
    assert dev.state == "opening"
    assert dev._arrival_due - dev._clock() == pytest.approx(6.0)
    assert _writes(bus) == [(CLOSED, False)]  # leaving a half-way stop: silence
    dev._clock.advance(6)
    dev._arrive()
    assert dev.state == "open"
    assert _writes(bus)[-1] == (OPENED, True)


def test_close_after_stop_goes_back():
    dev, bus, ctl = _setup()
    bus.inject(ACTION, "write", 0)
    dev._clock.advance(4)
    ctl.execute(Command("garage0", "stop"))
    bus.inject(ACTION, "write", 1)
    assert dev.state == "closing"
    assert dev._arrival_due - dev._clock() == pytest.approx(4.0)


def test_stop_when_idle_is_ignored(caplog):
    dev, bus, ctl = _setup()
    with caplog.at_level(logging.INFO):
        res = ctl.execute(Command("garage0", "stop"))
    assert res.ok and res.state["state"] == "closed"
    assert bus.writes == []
    assert any("'stop' ignored" in m for m in _infos(caplog))


# --- Inverted ----------------------------------------------------------------

def test_inverted_swaps_command_and_bit_status():
    dev, bus, _ = _setup({"Inverted": "true"})
    dev.publish_all_status()
    assert _writes(bus)[0] == (STATUS, False)  # closed, inverted: 0 = closed
    bus.inject(ACTION, "write", 1)  # inverted: 1 = open
    assert dev.state == "opening"
    dev._clock.advance(10)
    dev._arrive()
    assert (STATUS, True) in _writes(bus)  # inverted: 1 = open
    bus.inject(ACTION, "write", 0)  # inverted: 0 = close
    assert dev.state == "closing"


def test_inverted_does_not_touch_position_and_sensors():
    dev, bus, _ = _setup({"Inverted": "true"})
    bus.inject(ACTION, "write", 1)
    assert _writes(bus) == [(CLOSED, False)]
    dev._clock.advance(10)
    dev._arrive()
    assert _writes(bus)[1:] == [(STATUS, True), (POSITION, 100.0), (OPENED, True)]


def test_inverted_position_flips_the_percentage():
    dev, bus, _ = _setup({"InvertedPosition": "true"})
    dev.publish_all_status()
    assert (POSITION, 100.0) in _writes(bus)  # closed reported as 100 %
    bus.inject(ACTION, "write", 0)
    dev._clock.advance(10)
    dev._arrive()
    assert (POSITION, 0.0) in _writes(bus)  # open reported as 0 %
    assert dev.state_snapshot()["status_position"] == 0.0


def test_inverted_sensors_report_the_end_with_zero():
    dev, bus, _ = _setup({"InvertedSensorOpened": "true", "InvertedSensorClosed": "true"})
    dev.publish_all_status()
    assert _writes(bus)[2:] == [(OPENED, True), (CLOSED, False)]  # closed: NC contacts
    bus.inject(ACTION, "write", 0)
    assert _writes(bus)[-1] == (CLOSED, True)  # leaving the closed end: contact opens
    dev._clock.advance(10)
    dev._arrive()
    assert _writes(bus)[-1] == (OPENED, False)  # resting fully open: contact closed


def test_inverted_sensor_flags_are_independent():
    dev, bus, _ = _setup({"InvertedSensorOpened": "true"})
    dev.publish_all_status()
    assert _writes(bus)[2:] == [(OPENED, True), (CLOSED, True)]


# --- local commands ----------------------------------------------------------

def test_local_open_and_close():
    dev, bus, ctl = _setup()
    res = ctl.execute(Command("garage0", "open"))
    assert res.ok and res.state["state"] == "opening"
    assert _writes(bus) == [(CLOSED, False)]
    dev._clock.advance(10)
    dev._arrive()
    res = ctl.execute(Command("garage0", "close"))
    assert res.ok and res.state["state"] == "closing"
    assert _writes(bus)[-1] == (OPENED, False)


def test_available_commands():
    dev, _, _ = _setup()
    assert sorted(spec.name for spec in dev.available_commands()) == ["close", "open", "stop"]


# --- real timer ----------------------------------------------------------------

def test_arrival_timer_fires_in_the_event_loop():
    import time

    dev, bus, _ = _setup({"TravelSec": "0.05"})
    dev._clock = time.monotonic

    async def scenario():
        bus.inject(ACTION, "write", 0)
        assert dev.state == "opening"
        await asyncio.sleep(0.15)
        assert dev.state == "open"
        # reverse and stop the device while it is moving: the timer is cancelled
        bus.inject(ACTION, "write", 1)
        assert dev._timer is not None
        await dev.stop()
        assert dev._timer is None
        await asyncio.sleep(0.15)
        assert dev.state == "closing"  # no timer — nobody finished the travel

    asyncio.run(scenario())
    assert (OPENED, True) in _writes(bus)


def test_reverse_in_the_event_loop_replaces_the_timer():
    import time

    dev, bus, _ = _setup({"TravelSec": "0.1"})
    dev._clock = time.monotonic

    async def scenario():
        bus.inject(ACTION, "write", 0)
        first = dev._timer
        await asyncio.sleep(0.04)
        bus.inject(ACTION, "write", 1)
        assert first.cancelled()
        assert dev.state == "closing"
        await asyncio.sleep(0.12)
        assert dev.state == "closed"

    asyncio.run(scenario())
    assert _writes(bus)[-1] == (CLOSED, True)


# --- impulse mode (drive with a stop state) ----------------------------------

def test_impulse_off_by_default_keeps_the_motor_model():
    dev, bus, _ = _setup()
    bus.inject(ACTION, "write", 0)
    dev._clock.advance(4)
    bus.inject(ACTION, "write", 1)
    assert dev.state == "closing"


def test_impulse_while_moving_halts_whatever_the_bit():
    for bit in (0, 1):
        dev, bus, _ = _setup({"Impulse": "True"})
        bus.inject(ACTION, "write", 0)
        dev._clock.advance(4)  # 40 % open
        bus.inject(ACTION, "write", bit)
        assert dev.state == "stopped"
        assert dev.state_snapshot()["position"] == 40.0
        assert dev._timer is None
        assert _writes(bus) == [(CLOSED, False)]  # halting sends nothing


def test_impulse_while_standing_moves_as_the_bit_asks():
    dev, bus, _ = _setup({"Impulse": "True"})
    bus.inject(ACTION, "write", 0)
    dev._clock.advance(4)
    bus.inject(ACTION, "write", 1)  # halt at 40 %
    bus.inject(ACTION, "write", 1)  # second press: close from 40 %
    assert dev.state == "closing"
    assert dev._arrival_due - dev._clock() == pytest.approx(4.0)
    dev._clock.advance(4)
    dev._arrive()
    assert dev.state == "closed"
    assert _writes(bus)[-1] == (CLOSED, True)


# --- push button (PushButton = True) -----------------------------------------

@pytest.mark.parametrize("bit", [0, 1])
def test_push_at_the_closed_end_opens_whatever_the_bit(bit):
    dev, bus, _ = _setup({"PushButton": "True"})
    bus.inject(ACTION, "write", bit)
    assert dev.state == "opening"
    assert _writes(bus) == [(CLOSED, False)]


@pytest.mark.parametrize("bit", [0, 1])
def test_push_at_the_open_end_closes_whatever_the_bit(bit):
    dev, bus, _ = _setup({"PushButton": "True", "State": "open"})
    bus.inject(ACTION, "write", bit)
    assert dev.state == "closing"
    assert _writes(bus) == [(OPENED, False)]


def test_push_ignores_inverted():
    dev, bus, _ = _setup({"PushButton": "True", "Inverted": "true"})
    bus.inject(ACTION, "write", 0)  # as a command, inverted 0 = close: ignored at the closed end
    assert dev.state == "opening"


def test_push_cycle_open_close():
    dev, bus, _ = _setup({"PushButton": "True"})
    bus.inject(ACTION, "write", 1)
    dev._clock.advance(10)
    dev._arrive()
    assert dev.state == "open"
    bus.inject(ACTION, "write", 1)
    assert dev.state == "closing"
    dev._clock.advance(10)
    dev._arrive()
    assert dev.state == "closed"
    assert _writes(bus) == [
        (CLOSED, False), (STATUS, False), (POSITION, 100.0), (OPENED, True),
        (OPENED, False), (STATUS, True), (POSITION, 0.0), (CLOSED, True),
    ]


def test_push_while_moving_reverses_from_the_current_position():
    dev, bus, _ = _setup({"PushButton": "True"})
    bus.inject(ACTION, "write", 1)
    dev._clock.advance(4)  # 40 % open
    bus.inject(ACTION, "write", 1)
    assert dev.state == "closing"
    assert dev._arrival_due - dev._clock() == pytest.approx(4.0)
    dev._clock.advance(4)
    dev._arrive()
    assert dev.state == "closed"
    assert _writes(bus) == [
        (CLOSED, False), (STATUS, True), (POSITION, 0.0), (CLOSED, True),
    ]


def test_push_cycle_open_stop_close_stop_with_impulse(caplog):
    dev, bus, _ = _setup({"PushButton": "True", "Impulse": "True"})
    bus.inject(ACTION, "write", 1)  # open
    assert dev.state == "opening"
    dev._clock.advance(4)
    with caplog.at_level(logging.INFO):
        bus.inject(ACTION, "write", 1)  # stop at 40 %
    assert dev.state == "stopped"
    assert dev.state_snapshot()["position"] == 40.0
    assert any("push" in m and "halting" in m for m in _infos(caplog))
    bus.inject(ACTION, "write", 1)  # close: back from where it was heading
    assert dev.state == "closing"
    assert dev._arrival_due - dev._clock() == pytest.approx(4.0)
    dev._clock.advance(1)
    bus.inject(ACTION, "write", 1)  # stop at 30 %
    assert dev.state == "stopped"
    assert dev.state_snapshot()["position"] == pytest.approx(30.0)
    bus.inject(ACTION, "write", 1)  # open again
    assert dev.state == "opening"
    assert dev._arrival_due - dev._clock() == pytest.approx(7.0)
    assert _writes(bus) == [(CLOSED, False)]  # no end was reached in between


def test_push_after_a_half_way_stop_goes_back():
    dev, bus, ctl = _setup({"PushButton": "True"})
    bus.inject(ACTION, "write", 0)
    dev._clock.advance(4)
    ctl.execute(Command("garage0", "stop"))
    bus.inject(ACTION, "write", 0)
    assert dev.state == "closing"
    assert dev._arrival_due - dev._clock() == pytest.approx(4.0)


# --- two pulsed channels (ActionOpen / ActionClose) --------------------------

def _two_channels(extra=None):
    data = {"ActionOpen": ACTION_OPEN, "ActionClose": ACTION_CLOSE}
    data.update(extra or {})
    return _setup(data, remove=("Action",))


@pytest.mark.parametrize("value", [0, 1])
def test_any_telegram_on_the_open_channel_opens(value):
    dev, bus, _ = _two_channels()
    bus.inject(ACTION_OPEN, "write", value)
    assert dev.state == "opening"
    assert _writes(bus) == [(CLOSED, False)]
    dev._clock.advance(10)
    dev._arrive()
    assert dev.state == "open"
    assert _writes(bus)[1:] == [(STATUS, False), (POSITION, 100.0), (OPENED, True)]


@pytest.mark.parametrize("value", [0, 1])
def test_any_telegram_on_the_close_channel_closes(value):
    dev, bus, _ = _two_channels({"State": "open"})
    bus.inject(ACTION_CLOSE, "write", value)
    assert dev.state == "closing"
    assert _writes(bus) == [(OPENED, False)]
    dev._clock.advance(10)
    dev._arrive()
    assert dev.state == "closed"
    assert _writes(bus)[1:] == [(STATUS, True), (POSITION, 0.0), (CLOSED, True)]


def test_other_channel_while_moving_reverses():
    dev, bus, _ = _two_channels()
    bus.inject(ACTION_OPEN, "write", 1)
    dev._clock.advance(4)  # 40 % open
    bus.inject(ACTION_CLOSE, "write", 1)
    assert dev.state == "closing"
    assert dev._arrival_due - dev._clock() == pytest.approx(4.0)
    assert _writes(bus) == [(CLOSED, False)]


def test_same_channel_while_moving_is_ignored(caplog):
    dev, bus, _ = _two_channels()
    bus.inject(ACTION_OPEN, "write", 1)
    dev._clock.advance(3)
    with caplog.at_level(logging.INFO):
        bus.inject(ACTION_OPEN, "write", 1)
    assert any("ignored" in m and "already opening" in m for m in _infos(caplog))
    # the travel was not restarted
    assert dev._arrival_due - dev._clock() == 7.0


def test_open_channel_at_the_open_end_is_ignored(caplog):
    dev, bus, _ = _two_channels({"State": "open"})
    with caplog.at_level(logging.INFO):
        bus.inject(ACTION_OPEN, "write", 1)
    assert bus.writes == []
    assert dev.state == "open"
    assert any("ignored" in m and "already open" in m for m in _infos(caplog))


def test_two_channels_replace_the_action_object():
    dev, bus, _ = _setup({"ActionOpen": ACTION_OPEN, "ActionClose": ACTION_CLOSE})
    bus.inject(ACTION, "write", 0)  # Action is not listened to any more
    assert dev.state == "closed"
    bus.inject(ACTION_OPEN, "write", 0)
    assert dev.state == "opening"


def test_two_channels_need_both_addresses():
    # half a pair is an error even though Action is still in the config
    with pytest.raises(MissingOptionError):
        _setup({"ActionOpen": ACTION_OPEN})
    with pytest.raises(MissingOptionError):
        _setup({"ActionClose": ACTION_CLOSE})
