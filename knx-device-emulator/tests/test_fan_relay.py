"""Multi-winding fan: one relay GA per speed (DPT 1.001), passive.

The fan mirrors the relay commands and verifies the actuator's
break-before-make algorithm: on a speed change all the windings must be
switched off before the new one is switched on. Violations go to the log
as errors; the fan itself never switches anything off.
"""

import logging

import pytest

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.exceptions import InvalidValueError, MissingOptionError
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter

_BASE = {
    "type": "fan_relay",
    "Speeds": "3",
    "ActionSpeed1": "1/6/1", "StatusSpeed1": "2/6/1",
    "ActionSpeed2": "1/6/2", "StatusSpeed2": "2/6/2",
    "ActionSpeed3": "1/6/3", "StatusSpeed3": "2/6/3",
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
    mgr.build(AppConfig(knx={}, control={}, devices=[DeviceEntry("fan0", "fan_relay", cfg)]))
    return mgr.get_device("fan0"), bus, ControlInterface(mgr)


def _off_all(bus):
    for ga in ("1/6/1", "1/6/2", "1/6/3"):
        bus.inject(ga, "write", 0)


def _errors(caplog):
    return [r for r in caplog.records if r.levelno == logging.ERROR]


def test_registered_as_type():
    reg = DeviceRegistry(); reg.discover("devices")
    assert "fan_relay" in reg.types


def test_initial_speed_from_config():
    dev, bus, ctl = _setup({"Speed": "2"})
    assert dev.state_snapshot() == {"speed1": False, "speed2": True, "speed3": False}


def test_correct_algorithm_no_errors(caplog):
    dev, bus, ctl = _setup()
    with caplog.at_level(logging.INFO):
        bus.inject("1/6/2", "write", 1)   # start from idle
        _off_all(bus)                     # break ...
        bus.inject("1/6/3", "write", 1)   # ... before make
    assert _errors(caplog) == []
    assert dev.state_snapshot() == {"speed1": False, "speed2": False, "speed3": True}


def test_on_while_other_energized_logs_error_and_fan_keeps_both(caplog):
    dev, bus, ctl = _setup({"Speed": "2"})
    with caplog.at_level(logging.INFO):
        bus.inject("1/6/3", "write", 1)   # no OFFs at all
    errors = _errors(caplog)
    assert errors and "still energized" in errors[0].getMessage()
    # the fan is passive: winding 2 stays on, it does NOT switch it off itself
    assert dev.state_snapshot() == {"speed1": False, "speed2": True, "speed3": True}


def test_partial_off_before_switch_logs_error(caplog):
    dev, bus, ctl = _setup()
    with caplog.at_level(logging.INFO):
        bus.inject("1/6/2", "write", 1)
        bus.inject("1/6/2", "write", 0)   # only the active winding is switched off
        bus.inject("1/6/3", "write", 1)
    errors = _errors(caplog)
    assert len(errors) == 1
    assert "without OFF for winding(s) [1, 3]" in errors[0].getMessage()
    assert dev.state_snapshot() == {"speed1": False, "speed2": False, "speed3": True}


def test_stop_without_restart_is_fine(caplog):
    dev, bus, ctl = _setup({"Speed": "2"})
    with caplog.at_level(logging.INFO):
        bus.inject("1/6/2", "write", 0)
    assert _errors(caplog) == []
    assert dev.state_snapshot() == {"speed1": False, "speed2": False, "speed3": False}


def test_repeated_on_same_winding_is_not_a_switch(caplog):
    dev, bus, ctl = _setup()
    with caplog.at_level(logging.INFO):
        bus.inject("1/6/2", "write", 1)
        bus.inject("1/6/2", "write", 1)   # telegram repeat, no speed change
    assert _errors(caplog) == []


def test_off_inactive_winding_no_error(caplog):
    dev, bus, ctl = _setup({"Speed": "2"})
    with caplog.at_level(logging.INFO):
        bus.inject("1/6/1", "write", 0)
    assert _errors(caplog) == []
    assert dev.state_snapshot()["speed2"] is True


def test_status_of_winding_published_on_relay_command():
    dev, bus, ctl = _setup()
    bus.inject("1/6/2", "write", 1)
    assert bus.writes[-1][1] is True
    assert str(bus.writes[-1][0]) == "2/6/2"


def test_local_set_speed_and_reset_of_tracking(caplog):
    dev, bus, ctl = _setup()
    res = ctl.execute(Command("fan0", "set_speed", {"speed": 2}))
    assert res.state == {"speed": 2}
    assert dev.state_snapshot() == {"speed1": False, "speed2": True, "speed3": False}
    # a proper bus switch right after the local override raises no errors
    with caplog.at_level(logging.INFO):
        _off_all(bus)
        bus.inject("1/6/3", "write", 1)
    assert _errors(caplog) == []


def test_local_off():
    dev, bus, ctl = _setup({"Speed": "3"})
    res = ctl.execute(Command("fan0", "off"))
    assert res.state == {"speed": 0}
    assert dev.state_snapshot() == {"speed1": False, "speed2": False, "speed3": False}


def test_out_of_range_from_panel_is_rejected():
    dev, bus, ctl = _setup({"Speed": "1"})
    res = ctl.execute(Command("fan0", "set_speed", {"speed": 4}))
    assert not res.ok
    assert "0..3" in res.error
    assert dev.state_snapshot()["speed1"] is True  # unchanged


def test_speeds_out_of_range_rejected():
    with pytest.raises(InvalidValueError):
        _setup({"Speeds": "5"})
    with pytest.raises(InvalidValueError):
        _setup({"Speeds": "0"})


def test_initial_speed_out_of_range_rejected():
    with pytest.raises(InvalidValueError):
        _setup({"Speed": "4"})  # Speeds = 3


def test_action_ga_required_per_speed():
    with pytest.raises(MissingOptionError):
        _setup(remove=("ActionSpeed3",))


def test_statuses_are_optional(caplog):
    dev, bus, ctl = _setup(remove=("StatusSpeed1", "StatusSpeed2", "StatusSpeed3"))
    with caplog.at_level(logging.INFO):
        bus.inject("1/6/2", "write", 1)   # from idle — correct
        bus.inject("1/6/3", "write", 1)   # winding 2 still on — violation
    assert bus.writes == []               # nothing to broadcast without status GAs
    assert _errors(caplog)                # ...but the violation is still detected
