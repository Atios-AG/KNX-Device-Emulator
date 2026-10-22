"""Behaviour of the dimmer plugin's local commands: set_level, toggle and set."""

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter


def _setup(**extra):
    cfg = DeviceConfig("dim0", {
        "type": "dimmer",
        "Action": "1/2/1", "ActionDim": "1/2/2",
        "Status": "2/2/1", "StatusDim": "2/2/2",
        **extra,
    })
    reg = DeviceRegistry()
    reg.discover("devices")
    bus = FakeBusAdapter()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[DeviceEntry("dim0", "dimmer", cfg)]))
    return mgr.get_device("dim0"), bus, ControlInterface(mgr)


def test_set_level_turns_on_and_publishes_both_status_points():
    dev, bus, control = _setup()
    res = control.execute(Command("dim0", "set_level", {"level": 30}))
    assert res.ok
    assert res.state == {"on": True, "level": 30.0}
    assert bus.writes[-2:] == [(dev.status.ga, True), (dev.status_dim.ga, 30.0)]
    assert control.execute(Command("dim0", "set_level", {"level": 0})).state == {"on": False, "level": 0.0}


def test_set_on_restores_the_last_level_and_off_zeroes_it():
    dev, bus, control = _setup()
    control.execute(Command("dim0", "set_level", {"level": 40}))
    assert control.execute(Command("dim0", "set", {"on": False})).state == {"on": False, "level": 0.0}
    assert control.execute(Command("dim0", "set", {"on": True})).state == {"on": True, "level": 100.0}
    assert control.execute(Command("dim0", "set", {"on": True})).state == {"on": True, "level": 100.0}


def test_bus_write_on_the_dim_address_sets_the_level():
    dev, bus, control = _setup()
    bus.inject("1/2/2", "write", bytes([128]))
    snap = dev.state_snapshot()
    assert snap["on"] is True and abs(snap["level"] - 50.2) < 0.5


def test_initial_level_from_config():
    dev, bus, _ = _setup(Level="60")
    dev.publish_all_status()
    assert dev.state_snapshot() == {"on": True, "level": 60.0}
    assert [v for _, v in bus.writes] == [True, 60.0]


def test_level_only_without_an_on_off_object():
    cfg = DeviceConfig("d1", {"type": "dimmer", "ActionDim": "1/2/2", "StatusDim": "2/2/2", "Level": "40"})
    reg = DeviceRegistry(); reg.discover("devices")
    bus = FakeBusAdapter()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[DeviceEntry("d1", "dimmer", cfg)]))
    bus.inject("1/2/2", "write", bytes([0]))
    assert mgr.get_device("d1").state_snapshot() == {"on": False, "level": 0.0}
    assert [str(ga) for ga, _ in bus.writes] == ["2/2/2"]
