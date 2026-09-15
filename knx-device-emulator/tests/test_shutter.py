"""Roller shutter: Up/Down + Stop + absolute target, position reported at rest (0 % = open)."""

import logging

import pytest

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import ControlInterface
from core.device_manager import DeviceManager
from core.exceptions import InvalidValueError, MissingOptionError
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter

MOVE, STOP, TARGET, CURRENT, MOVE_STATUS = "3/1/1", "3/1/3", "3/1/4", "3/1/5", "3/1/2"

_BASE = {
    "type": "shutter",
    "Movement": MOVE,
    "Stop": STOP,
    "TargetPosition": TARGET,
    "CurrentPosition": CURRENT,
    "StatusMovement": MOVE_STATUS,
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
    cfg = DeviceConfig("shutter0", data)
    reg = DeviceRegistry(); reg.discover("devices")
    bus = FakeBusAdapter()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[DeviceEntry("shutter0", "shutter", cfg)]))
    dev = mgr.get_device("shutter0")
    dev._clock = FakeClock()
    return dev, bus, ControlInterface(mgr)


def _writes(bus):
    return [(str(ga), value) for ga, value in bus.writes]


def test_registered_as_type():
    reg = DeviceRegistry(); reg.discover("devices")
    assert "shutter" in reg.types


def test_initial_state_open():
    dev, bus, _ = _setup()
    dev.publish_all_status()
    assert dev.state_snapshot()["position"] == 0.0
    assert _writes(bus) == [(CURRENT, 0.0), (MOVE_STATUS, False)]


def test_initial_position_from_config():
    dev, bus, _ = _setup({"Position": "100"})
    dev.publish_all_status()
    assert _writes(bus) == [(CURRENT, 100.0), (MOVE_STATUS, True)]


def test_movement_required():
    with pytest.raises(MissingOptionError):
        _setup(remove=("Movement",))


def test_bad_position_rejected():
    with pytest.raises(InvalidValueError):
        _setup({"Position": "120"})


def test_down_then_arrival_reports_closed():
    dev, bus, _ = _setup()
    bus.inject(MOVE, "write", 1)
    assert dev.state == "closing"
    assert _writes(bus) == []  # nothing until the drive rests
    dev._clock.advance(10)
    dev._arrive()
    assert _writes(bus) == [(CURRENT, 100.0), (MOVE_STATUS, True)]


def test_absolute_target_and_proportional_time():
    dev, bus, _ = _setup()
    bus.inject(TARGET, "write", bytes([128]))  # 50.2 % on the wire
    assert dev.state == "closing"
    dev._clock.advance(5)
    assert abs(dev.current_position() - 50.0) < 0.5
    dev._arrive()
    assert _writes(bus) == [(CURRENT, 50.2), (MOVE_STATUS, False)]


def test_stop_halfway_reports_position():
    dev, bus, _ = _setup()
    bus.inject(MOVE, "write", 1)
    dev._clock.advance(3)
    bus.inject(STOP, "write", 1)
    assert dev.state == "idle"
    assert _writes(bus)[-2:] == [(CURRENT, 30.0), (MOVE_STATUS, False)]


def test_reverse_while_moving():
    dev, bus, _ = _setup()
    bus.inject(MOVE, "write", 1)
    dev._clock.advance(4)
    bus.inject(MOVE, "write", 0)
    assert dev.state == "opening"
    dev._clock.advance(4)
    dev._arrive()
    assert _writes(bus)[-2:] == [(CURRENT, 0.0), (MOVE_STATUS, False)]


def test_same_target_is_ignored(caplog):
    caplog.set_level(logging.INFO)
    dev, bus, _ = _setup()
    bus.inject(MOVE, "write", 0)
    assert dev.state == "idle" and _writes(bus) == []
    assert any("ignored" in r.getMessage() for r in caplog.records)


def test_local_commands():
    dev, bus, ctl = _setup()
    dev.cmd_down()
    assert dev.state == "closing"
    dev.cmd_stop()
    assert dev.state == "idle"
    dev.cmd_position(percent=25)
    assert dev.state == "closing"
    dev._clock.advance(10)
    dev._arrive()
    assert dev.state_snapshot()["position"] == 25.0
    dev.cmd_up()
    assert dev.state == "opening"
