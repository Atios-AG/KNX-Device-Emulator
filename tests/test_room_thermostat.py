"""Room thermostat: configurable mode bytes, a 1-bit mode, on/off and season."""

import pytest

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.exceptions import InvalidValueError
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter

GA = {"ActionSetpoint": "1/4/1", "StatusSetpoint": "1/4/2", "StatusCurrent": "1/4/3", "ActionOnOff": "1/4/4",
      "StatusOnOff": "1/4/5", "ActionMode": "1/4/6", "StatusMode": "1/4/7", "StatusSeason": "1/4/8"}
BYTES = {"ModeOff": "6", "ModeHeat": "1", "ModeCool": "3", "ModeAuto": "0"}


def _setup(keys=GA, **extra):
    data = {"type": "room_thermostat", **keys, **extra}
    cfg = DeviceConfig("th0", data)
    reg = DeviceRegistry(); reg.discover("devices")
    bus = FakeBusAdapter()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[DeviceEntry("th0", "room_thermostat", cfg)]))
    return mgr.get_device("th0"), bus, ControlInterface(mgr)


def _written(bus):
    return {str(ga): v for ga, v in bus.writes}


def test_mode_byte_switches_on_without_an_onoff_object():
    keys = {k: v for k, v in GA.items() if "OnOff" not in k and "Season" not in k}
    dev, bus, _ = _setup(keys, On="false", **BYTES)
    bus.inject("1/4/6", "write", bytes([3]))
    assert dev.state_snapshot()["on"] is True and dev.state_snapshot()["mode"] == "cool"
    assert _written(bus)["1/4/7"] == 3
    bus.inject("1/4/6", "write", bytes([6]))
    assert dev.state_snapshot()["on"] is False
    assert bus.last_write_value() == 6                 # the off byte while off


def test_with_an_onoff_object_power_follows_it_and_the_mode_stays():
    dev, bus, _ = _setup(On="false", **BYTES)
    bus.inject("1/4/6", "write", bytes([3]))
    assert dev.state_snapshot()["on"] is False and dev.state_snapshot()["mode"] == "cool"
    bus.inject("1/4/4", "write", 1)
    assert dev.state_snapshot()["on"] is True
    bus.inject("1/4/6", "write", bytes([6]))           # the off byte still switches off
    assert dev.state_snapshot()["on"] is False
    assert bus.last_write_value() == 3                  # StatusMode keeps the mode, power is StatusOnOff


def test_only_changed_statuses_and_the_echo_are_sent():
    dev, bus, _ = _setup(**BYTES)
    bus.writes.clear()
    bus.inject("1/4/1", "write", b"\x0c\x9a")           # 23.0 °C
    assert [str(ga) for ga, _ in bus.writes] == ["1/4/2"]
    bus.writes.clear()
    bus.inject("1/4/4", "write", 1)                     # already on: only the echo
    assert [str(ga) for ga, _ in bus.writes] == ["1/4/5"]


def test_unknown_mode_byte_is_ignored():
    dev, bus, _ = _setup(**BYTES)
    bus.inject("1/4/6", "write", bytes([9]))
    assert dev.state_snapshot()["mode"] == "heat" and dev.state_snapshot()["on"] is True


def test_mode_bit():
    keys = {k: GA[k] for k in ("ActionSetpoint", "ActionMode", "StatusMode")}
    dev, bus, ctl = _setup(keys, ModeBit="true", Mode="cool")
    bus.inject("1/4/6", "write", 0)
    assert dev.state_snapshot()["on"] is False and bus.last_write_value() == 0
    ctl.execute(Command("th0", "set_mode", {"mode": "cool"}))
    assert bus.last_write_value() == 1


def test_season_sets_the_direction_and_can_be_inverted():
    dev, bus, ctl = _setup(SeasonInverted="true", **BYTES)
    state = ctl.execute(Command("th0", "set_season", {"season": "summer"})).state
    assert state["mode"] == "cool" and state["on"] is True
    assert _written(bus)["1/4/8"] == 1                  # summer, inverted
    ctl.execute(Command("th0", "set_mode", {"mode": "auto"}))
    assert ctl.execute(Command("th0", "set_season", {"season": "winter"})).state["mode"] == "auto"


def test_panel_commands():
    dev, bus, ctl = _setup(**BYTES)
    assert ctl.execute(Command("th0", "set_mode", {"mode": "off"})).state["on"] is False
    state = ctl.execute(Command("th0", "set_mode", {"mode": "auto"})).state
    assert state["on"] is True and state["mode"] == "auto" and _written(bus)["1/4/7"] == 0
    assert ctl.execute(Command("th0", "set_current", {"value": 19.5})).state["current"] == 19.5
    assert ctl.execute(Command("th0", "set_setpoint", {"value": 24.5})).state["setpoint"] == 24.5
    assert ctl.execute(Command("th0", "set_onoff", {"on": False})).state["on"] is False


def test_config_errors():
    with pytest.raises(InvalidValueError):
        _setup(ModeOff="1", ModeHeat="1", ModeCool="3")
    with pytest.raises(InvalidValueError):
        _setup(Mode="auto", ModeHeat="1", ModeCool="3")
