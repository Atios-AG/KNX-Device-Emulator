"""rgbw_light: on/off and red, green, blue, white each as 0..100 %."""

import pytest

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.exceptions import InvalidValueError
from core.registry import DeviceRegistry
from tests.test_color_light import WireBus

GA = {"Action": "1/6/1", "Status": "1/6/2", "ActionRed": "1/6/3", "StatusRed": "1/6/4",
      "ActionGreen": "1/6/5", "StatusGreen": "1/6/6", "ActionBlue": "1/6/7", "StatusBlue": "1/6/8",
      "ActionWhite": "1/6/9", "StatusWhite": "1/6/10"}
RGB = {k: v for k, v in GA.items() if not k.endswith("White")}


def _setup(keys=GA, **extra):
    cfg = DeviceConfig("strip", {"type": "rgbw_light", **keys, **extra})
    reg = DeviceRegistry(); reg.discover("devices")
    bus = WireBus()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[DeviceEntry("strip", "rgbw_light", cfg)]))
    return mgr.get_device("strip"), bus, ControlInterface(mgr)


def _sent(bus):
    """The last telegram per address, as wire bytes."""
    return {ga: raw for ga, raw in bus.wire}


def test_a_channel_write_switches_on_and_is_echoed_also_unchanged():
    dev, bus, _ = _setup()
    bus.inject("1/6/3", "write", bytes([255]))
    assert dev.state_snapshot() == {"on": True, "red": 100.0, "green": 0.0, "blue": 0.0, "white": 0.0}
    assert _sent(bus) == {"1/6/4": bytes([255]), "1/6/2": 1}
    bus.wire.clear()
    bus.inject("1/6/3", "write", bytes([255]))
    assert bus.wire == [("1/6/4", bytes([255]))]                 # only the echo


@pytest.mark.parametrize("byte", range(256))
def test_every_channel_byte_comes_back_unchanged(byte):
    dev, bus, _ = _setup()
    bus.inject("1/6/9", "write", bytes([byte]))
    assert ("1/6/10", bytes([byte])) in bus.wire


def test_the_last_channel_at_zero_switches_off():
    dev, bus, _ = _setup(Red="50", White="20")
    bus.inject("1/6/3", "write", bytes([0]))
    assert dev.state_snapshot()["on"] is True
    bus.inject("1/6/9", "write", bytes([0]))
    assert dev.state_snapshot()["on"] is False
    assert _sent(bus)["1/6/2"] == 0


def test_off_reports_zero_and_on_brings_back_the_channels():
    dev, bus, _ = _setup(Red="40", Green="20", Blue="0", White="60")
    bus.inject("1/6/1", "write", 0)
    assert dev.state_snapshot() == {"on": False, "red": 0.0, "green": 0.0, "blue": 0.0, "white": 0.0}
    assert _sent(bus)["1/6/4"] == bytes([0]) and _sent(bus)["1/6/10"] == bytes([0])
    bus.inject("1/6/1", "write", 1)
    assert dev.state_snapshot() == {"on": True, "red": 40.0, "green": 20.0, "blue": 0.0, "white": 60.0}
    assert _sent(bus)["1/6/10"] == bytes([153])


def test_on_the_first_time_is_every_channel_at_full():
    dev, _, _ = _setup()
    assert dev.state_snapshot() == {"on": False, "red": 0.0, "green": 0.0, "blue": 0.0, "white": 0.0}
    dev.cmd_set(True)
    assert dev.state_snapshot() == {"on": True, "red": 100.0, "green": 100.0, "blue": 100.0, "white": 100.0}


def test_without_a_white_address_it_is_an_rgb_light():
    dev, bus, control = _setup(RGB, Red="10")
    assert dev.state_snapshot() == {"on": True, "red": 10.0, "green": 0.0, "blue": 0.0}
    assert not control.execute(Command("strip", "set_rgbw", {"red": 0, "green": 0, "blue": 0, "white": 50})).ok
    assert control.execute(Command("strip", "set_rgbw", {"red": 0, "green": 30, "blue": 0, "white": 0})).ok


def test_initial_values_are_broadcast_and_answer_a_read():
    dev, bus, _ = _setup(Red="80", Green="20", White="40")
    dev.publish_all_status()
    assert _sent(bus) == {"1/6/2": 1, "1/6/4": bytes([204]), "1/6/6": bytes([51]), "1/6/8": bytes([0]),
                          "1/6/10": bytes([102])}
    bus.inject("1/6/6", "read", None)
    assert bus.wire_responses == [("1/6/6", bytes([51]))]


def test_panel_commands_publish_what_changed():
    dev, bus, control = _setup(White="50")
    bus.wire.clear()
    state = control.execute(Command("strip", "set_rgbw", {"red": 100, "green": 0, "blue": 0, "white": 50})).state
    assert state == {"on": True, "red": 100.0, "green": 0.0, "blue": 0.0, "white": 50.0}
    assert {ga for ga, _ in bus.wire} == {"1/6/4"}
    assert control.execute(Command("strip", "set", {"on": False})).state["on"] is False
    assert control.execute(Command("strip", "toggle", {})).state == state


@pytest.mark.parametrize("args", [{"red": 101, "green": 0, "blue": 0, "white": 0},
                                  {"red": 0, "green": -1, "blue": 0, "white": 0}])
def test_a_panel_value_outside_0_to_100_is_refused(args):
    _, _, control = _setup()
    assert not control.execute(Command("strip", "set_rgbw", args)).ok


def test_an_initial_value_outside_0_to_100_is_a_config_error():
    with pytest.raises(InvalidValueError):
        _setup(Blue="120")
