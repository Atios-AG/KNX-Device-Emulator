"""Behaviour of the binary_sensor plugin: status-only, local set/toggle, Inverted, Read."""

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter


def _setup(inverted=False):
    cfg = DeviceConfig("motion0", {
        "type": "binary_sensor",
        "Status": "3/0/1",
        "Inverted": str(inverted),
    })
    reg = DeviceRegistry()
    reg.discover("devices")
    bus = FakeBusAdapter()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[
        DeviceEntry("motion0", "binary_sensor", cfg)
    ]))
    return mgr, bus, ControlInterface(mgr)


def test_starts_idle():
    mgr, bus, control = _setup()
    assert mgr.get_device("motion0").state_snapshot() == {"on": False}


def test_local_set_publishes_the_status():
    mgr, bus, control = _setup()
    res = control.execute(Command("motion0", "set", {"on": True}))
    assert res.ok
    assert res.state == {"on": True}
    assert bus.last_write_value() == 1
    res = control.execute(Command("motion0", "set", {"on": False}))
    assert res.state == {"on": False}
    assert bus.last_write_value() == 0


def test_local_toggle():
    mgr, bus, control = _setup()
    assert control.execute(Command("motion0", "toggle")).state == {"on": True}
    assert control.execute(Command("motion0", "toggle")).state == {"on": False}


def test_inverted_bus_value():
    mgr, bus, control = _setup(inverted=True)
    res = control.execute(Command("motion0", "set", {"on": True}))
    assert res.state == {"on": False}       # detected, carried as 0 on the bus
    assert bus.last_write_value() == 0


def test_read_is_answered_with_the_current_state():
    mgr, bus, control = _setup()
    control.execute(Command("motion0", "set", {"on": True}))
    bus.inject("3/0/1", "read", None)
    assert bus.responses[-1][1] == 1


def test_a_write_to_the_status_address_does_not_change_the_sensor():
    mgr, bus, control = _setup()
    bus.inject("3/0/1", "write", 1)
    assert mgr.get_device("motion0").state_snapshot() == {"on": False}
