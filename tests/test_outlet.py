"""Behaviour of the outlet plugin, including local commands (panel) and Inverted."""

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter


def _setup(inverted=False):
    cfg = DeviceConfig("outlet0", {
        "type": "outlet",
        "Action": "1/1/1",
        "Status": "2/2/2",
        "Inverted": str(inverted),
    })
    reg = DeviceRegistry()
    reg.discover("devices")
    bus = FakeBusAdapter()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[
        DeviceEntry("outlet0", "outlet", cfg)
    ]))
    return mgr, bus, ControlInterface(mgr)


def test_local_toggle_changes_state_and_emits():
    mgr, bus, control = _setup()
    res = control.execute(Command("outlet0", "toggle"))
    assert res.ok
    assert res.state == {"on": True}
    assert bus.last_write_value() == 1  # the status was sent to the bus


def test_local_set():
    mgr, bus, control = _setup()
    res = control.execute(Command("outlet0", "set", {"on": True}))
    assert res.state == {"on": True}
    res = control.execute(Command("outlet0", "set", {"on": False}))
    assert res.state == {"on": False}


def test_inverted_status():
    mgr, bus, control = _setup(inverted=True)
    # physically switching on -> the status on the bus is inverted (False)
    res = control.execute(Command("outlet0", "set", {"on": True}))
    assert res.state == {"on": False}
    assert bus.last_write_value() == 0


def test_unknown_command():
    mgr, bus, control = _setup()
    res = control.execute(Command("outlet0", "explode"))
    assert not res.ok
    assert "explode" in res.error


def test_unknown_device():
    mgr, bus, control = _setup()
    res = control.execute(Command("ghost", "toggle"))
    assert not res.ok


def test_describe_lists_commands():
    mgr, bus, control = _setup()
    info = control.describe_device("outlet0")
    names = {c["name"] for c in info["commands"]}
    assert {"toggle", "set"} <= names
