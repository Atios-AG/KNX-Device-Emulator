"""Behaviour of the analog_sensor plugin: status-only, initial value, local set, Read."""

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter


def _setup(value=None):
    data = {"type": "analog_sensor", "Status": "4/0/1"}
    if value is not None:
        data["Value"] = str(value)
    cfg = DeviceConfig("temp0", data)
    reg = DeviceRegistry()
    reg.discover("devices")
    bus = FakeBusAdapter()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[
        DeviceEntry("temp0", "analog_sensor", cfg)
    ]))
    return mgr, bus, ControlInterface(mgr)


def test_default_and_configured_initial_value():
    mgr, bus, control = _setup()
    assert mgr.get_device("temp0").state_snapshot() == {"value": 0.0}
    mgr, bus, control = _setup(value=21.5)
    assert mgr.get_device("temp0").state_snapshot() == {"value": 21.5}


def test_local_set_publishes_the_value():
    mgr, bus, control = _setup()
    res = control.execute(Command("temp0", "set", {"value": 18.25}))
    assert res.ok
    assert res.state == {"value": 18.25}
    assert bus.last_write_value() == 18.25


def test_read_is_answered_with_the_current_value():
    mgr, bus, control = _setup(value=22.0)
    bus.inject("4/0/1", "read", None)
    assert bus.responses[-1][1] == 22.0


def test_a_write_to_the_status_address_does_not_change_the_sensor():
    mgr, bus, control = _setup(value=22.0)
    bus.inject("4/0/1", "write", bytes([0x0C, 0x1A]))
    assert mgr.get_device("temp0").state_snapshot() == {"value": 22.0}
