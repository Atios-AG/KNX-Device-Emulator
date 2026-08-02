import asyncio

import pytest

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.device_manager import DeviceManager
from core.exceptions import DuplicateAddressError
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter


def _registry():
    reg = DeviceRegistry()
    reg.discover("devices")
    return reg


def _outlet_entry(name, action, status, inverted=False):
    cfg = DeviceConfig(name, {
        "type": "outlet",
        "Action": action,
        "Status": status,
        "Inverted": str(inverted),
    })
    return DeviceEntry(name=name, type="outlet", config=cfg)


def _manager(entries):
    bus = FakeBusAdapter()
    mgr = DeviceManager(_registry(), bus)
    mgr.build(AppConfig(knx={}, control={}, devices=entries))
    return mgr, bus


def test_write_triggers_action_and_status_published():
    mgr, bus = _manager([_outlet_entry("outlet0", "1/1/1", "2/2/2")])
    # a Write arrives at the Action address -> the device switches on and sends the status
    bus.inject("1/1/1", "write", 1)
    assert bus.last_write_value() == 1  # the status on 2/2/2


def test_read_produces_response():
    mgr, bus = _manager([_outlet_entry("outlet0", "1/1/1", "2/2/2")])
    bus.inject("2/2/2", "read", None)
    assert len(bus.responses) == 1
    assert str(bus.responses[0][0]) == "2/2/2"


def test_duplicate_action_address():
    with pytest.raises(DuplicateAddressError):
        _manager([
            _outlet_entry("a", "1/1/1", "2/2/1"),
            _outlet_entry("b", "1/1/1", "2/2/2"),
        ])


def test_get_device_by_name():
    mgr, _ = _manager([_outlet_entry("outlet0", "1/1/1", "2/2/2")])
    assert mgr.get_device("outlet0") is not None
    assert mgr.get_device("nope") is None


def test_initial_status_broadcast_on_start():
    mgr, bus = _manager([_outlet_entry("outlet0", "1/1/1", "2/2/2")])
    assert bus.writes == []  # nothing went on the bus before the start
    asyncio.run(mgr.start_all())
    assert any(str(ga) == "2/2/2" for ga, _ in bus.writes)  # the status was broadcast
    asyncio.run(mgr.stop_all())
