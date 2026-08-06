"""Step fan: the speed is a step number 0..Speeds sent as one byte (DPT 5.010)."""

import pytest

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.dpt import DPT_UCOUNT
from core.exceptions import InvalidValueError
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter

_BASE = {
    "type": "fan",
    "ActionFan": "1/5/1",
    "StatusFan": "2/5/1",
    "Speeds": "3",
}


def _setup(extra=None, remove=()):
    data = dict(_BASE)
    if extra:
        data.update(extra)
    for key in remove:
        data.pop(key, None)
    cfg = DeviceConfig("fan0", data)
    reg = DeviceRegistry(); reg.discover("devices")
    bus = FakeBusAdapter()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[DeviceEntry("fan0", "fan", cfg)]))
    return mgr.get_device("fan0"), bus, ControlInterface(mgr)


def test_registered_as_type():
    reg = DeviceRegistry(); reg.discover("devices")
    assert "fan" in reg.types


def test_initial_speed_from_config():
    dev, bus, ctl = _setup({"Speed": "2"})
    assert dev.state_snapshot() == {"speed": 2}


def test_set_speed_local_and_status_published():
    dev, bus, ctl = _setup()
    s = ctl.execute(Command("fan0", "set_speed", {"speed": 2})).state
    assert s == {"speed": 2}
    assert bus.last_write_value() == 2


def test_speed_from_bus_as_byte():
    dev, bus, ctl = _setup()
    bus.inject("1/5/1", "write", DPT_UCOUNT.encode(3))
    assert dev.state_snapshot()["speed"] == 3


def test_out_of_range_from_bus_is_discarded():
    dev, bus, ctl = _setup({"Speed": "1"})  # Speeds = 3
    bus.inject("1/5/1", "write", DPT_UCOUNT.encode(255))
    assert dev.state_snapshot()["speed"] == 1  # unchanged
    assert bus.writes == []  # no status broadcast either


def test_out_of_range_from_panel_is_rejected():
    dev, bus, ctl = _setup({"Speed": "1"})  # Speeds = 3
    res = ctl.execute(Command("fan0", "set_speed", {"speed": 9}))
    assert not res.ok
    assert "0..3" in res.error
    assert dev.state_snapshot()["speed"] == 1  # unchanged


def test_off_command():
    dev, bus, ctl = _setup({"Speed": "3"})
    s = ctl.execute(Command("fan0", "off")).state
    assert s == {"speed": 0}
    assert bus.last_write_value() == 0


def test_default_four_speeds():
    dev, bus, ctl = _setup(remove=("Speeds",))
    s = ctl.execute(Command("fan0", "set_speed", {"speed": 4})).state
    assert s == {"speed": 4}


def test_speeds_out_of_range_rejected():
    with pytest.raises(InvalidValueError):
        _setup({"Speeds": "5"})
    with pytest.raises(InvalidValueError):
        _setup({"Speeds": "0"})


def test_initial_speed_out_of_range_rejected():
    with pytest.raises(InvalidValueError):
        _setup({"Speed": "4"})  # Speeds = 3


def test_status_is_optional():
    dev, bus, ctl = _setup(remove=("StatusFan",))
    bus.inject("1/5/1", "write", DPT_UCOUNT.encode(2))
    assert dev._speed == 2
    assert bus.writes == []  # nothing is broadcast without a StatusFan
