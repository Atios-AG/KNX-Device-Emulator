"""Air conditioner: inherits the thermostat logic + a fan (percent 0..100)."""

import pytest

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.dpt import DPT_SCALING
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter

_BASE = {
    "type": "air_conditioner",
    "ActionOnOff": "1/4/1", "StatusOnOff": "2/4/1",
    "ActionSetpoint": "1/4/2", "StatusSetpoint": "2/4/2",
    "StatusCurrent": "2/4/3",
    "ActionMode": "1/4/4", "StatusMode": "2/4/4",
    "ActionFan": "1/4/5", "StatusFan": "2/4/5",
    "Fan": "0",
}


def _setup(extra=None):
    data = dict(_BASE)
    if extra:
        data.update(extra)
    cfg = DeviceConfig("ac", data)
    reg = DeviceRegistry(); reg.discover("devices")
    bus = FakeBusAdapter()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[DeviceEntry("ac", "air_conditioner", cfg)]))
    return mgr.get_device("ac"), bus, ControlInterface(mgr)


def test_registered_as_separate_type():
    reg = DeviceRegistry(); reg.discover("devices")
    assert "air_conditioner" in reg.types
    assert "thermostat" in reg.types  # the base type is in place too


def test_inherits_thermostat_commands_plus_fan():
    dev, bus, ctl = _setup()
    names = {c["name"] for c in ctl.describe_device("ac")["commands"]}
    assert {"set_onoff", "set_mode", "set_setpoint", "set_season"} <= names  # inherited
    assert "set_fan" in names  # added


def test_state_includes_fan():
    dev, bus, ctl = _setup()
    assert "fan" in dev.state_snapshot()


def test_climate_logic_still_works():
    dev, bus, ctl = _setup()
    s = ctl.execute(Command("ac", "set_mode", {"mode": "heat"})).state
    assert s["on"] is True and s["mode"] == "heat"


def test_set_fan_local_and_status_published():
    dev, bus, ctl = _setup()
    s = ctl.execute(Command("ac", "set_fan", {"level": 70})).state
    assert s["fan"] == pytest.approx(70, abs=1)
    assert bus.last_write_value() == pytest.approx(70, abs=1)


def test_fan_clamped_to_100():
    dev, bus, ctl = _setup()
    s = ctl.execute(Command("ac", "set_fan", {"level": 150})).state
    assert s["fan"] == 100.0


def test_fan_from_bus():
    dev, bus, ctl = _setup()
    bus.inject("1/4/5", "write", DPT_SCALING.encode(30))
    assert dev.state_snapshot()["fan"] == pytest.approx(30, abs=1)
