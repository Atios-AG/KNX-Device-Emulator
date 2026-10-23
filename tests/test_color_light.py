"""color_light: on/off, brightness, color temperature in Kelvin or as the
cold white share in %, and color as H, S, V in one 3-byte object."""

import pytest

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.exceptions import InvalidValueError
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter

GA = {"Action": "1/5/1", "Status": "1/5/2", "ActionDim": "1/5/3", "StatusDim": "1/5/4",
      "ActionKelvin": "1/5/5", "StatusKelvin": "1/5/6", "ActionColorTemp": "1/5/7", "StatusColorTemp": "1/5/8",
      "ActionHSV": "1/5/9", "StatusHSV": "1/5/10"}


class WireBus(FakeBusAdapter):
    """Also keeps every telegram as the bytes the DPT puts on the wire."""

    def __init__(self):
        super().__init__()
        self.wire, self.wire_responses = [], []

    def schedule_write(self, ga, dpt, value):
        super().schedule_write(ga, dpt, value)
        self.wire.append((str(ga), dpt.encode(value)))

    def schedule_response(self, ga, dpt, value):
        super().schedule_response(ga, dpt, value)
        self.wire_responses.append((str(ga), dpt.encode(value)))


def _setup(keys=GA, **extra):
    cfg = DeviceConfig("lamp", {"type": "color_light", **keys, **extra})
    reg = DeviceRegistry(); reg.discover("devices")
    bus = WireBus()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[DeviceEntry("lamp", "color_light", cfg)]))
    return mgr.get_device("lamp"), bus, ControlInterface(mgr)


def _sent(bus):
    """The last telegram per address, as wire bytes."""
    return {ga: raw for ga, raw in bus.wire}


def _only(*names):
    return {k: v for k, v in GA.items() if any(k.endswith(n) for n in names)}


# --- color temperature ------------------------------------------------------
def test_kelvin_write_sets_the_temperature_and_is_echoed_also_unchanged():
    dev, bus, _ = _setup(_only("ion", "atus", "Kelvin"))
    bus.inject("1/5/5", "write", bytes([0x0F, 0xA0]))        # 4000 K
    assert dev.state_snapshot()["kelvin"] == 4000
    assert _sent(bus) == {"1/5/6": bytes([0x0F, 0xA0])}
    bus.wire.clear()
    bus.inject("1/5/5", "write", bytes([0x0F, 0xA0]))
    assert bus.wire == [("1/5/6", bytes([0x0F, 0xA0]))]       # only the echo


def test_kelvin_outside_the_range_is_clamped():
    dev, bus, _ = _setup(WarmKelvin="3000", ColdKelvin="5000")
    bus.inject("1/5/5", "write", (2000).to_bytes(2, "big"))
    assert dev.state_snapshot()["kelvin"] == 3000
    bus.inject("1/5/5", "write", (10000).to_bytes(2, "big"))
    assert dev.state_snapshot()["kelvin"] == 5000
    assert _sent(bus)["1/5/6"] == (5000).to_bytes(2, "big")


def test_percent_is_the_cold_white_share_and_moves_the_kelvin_status():
    dev, bus, _ = _setup()                                     # 2700 .. 6500 K
    bus.inject("1/5/7", "write", bytes([0]))
    assert dev.state_snapshot()["kelvin"] == 2700
    bus.inject("1/5/7", "write", bytes([255]))
    assert dev.state_snapshot()["kelvin"] == 6500
    assert _sent(bus)["1/5/8"] == bytes([255]) and _sent(bus)["1/5/6"] == (6500).to_bytes(2, "big")
    bus.inject("1/5/7", "write", bytes([43]))                  # 16.9 % -> 3342 K
    assert dev.state_snapshot()["kelvin"] == 3342
    assert _sent(bus)["1/5/8"] == bytes([43])                  # the status gives back the same byte


@pytest.mark.parametrize("byte", range(256))
def test_every_percent_byte_comes_back_unchanged(byte):
    dev, bus, _ = _setup(_only("ColorTemp"))
    bus.inject("1/5/7", "write", bytes([byte]))
    assert bus.wire[-1] == ("1/5/8", bytes([byte]))


def test_a_kelvin_write_moves_the_percent_status():
    dev, bus, _ = _setup()
    bus.inject("1/5/5", "write", (4600).to_bytes(2, "big"))   # 50 % of 2700 .. 6500
    assert _sent(bus)["1/5/8"] == bytes([128])


def test_color_temperature_does_not_switch_the_light_on():
    dev, bus, _ = _setup(Level="0")
    bus.inject("1/5/5", "write", (5000).to_bytes(2, "big"))
    assert dev.state_snapshot()["on"] is False and dev.state_snapshot()["kelvin"] == 5000


# --- HSV ---------------------------------------------------------------------
def test_hsv_write_sets_hue_saturation_and_brightness():
    dev, bus, _ = _setup(Level="0")
    bus.inject("1/5/9", "write", bytes([85, 255, 128]))
    snap = dev.state_snapshot()
    assert snap["on"] is True
    assert snap["hue"] == pytest.approx(120, abs=0.1)
    assert snap["saturation"] == pytest.approx(100, abs=0.1)
    assert snap["level"] == pytest.approx(50.2, abs=0.1)
    assert _sent(bus) == {"1/5/10": bytes([85, 255, 128]), "1/5/2": 1, "1/5/4": bytes([128])}


@pytest.mark.parametrize("hsv", [(0, 0, 1), (85, 255, 128), (170, 128, 191), (255, 1, 255), (42, 77, 13)])
def test_hsv_status_gives_back_the_written_bytes(hsv):
    dev, bus, _ = _setup(_only("HSV"))
    bus.inject("1/5/9", "write", bytes(hsv))
    assert bus.wire[-1] == ("1/5/10", bytes(hsv))


def test_value_zero_switches_off_and_on_brings_back_color_and_brightness():
    dev, bus, _ = _setup()
    bus.inject("1/5/9", "write", bytes([170, 128, 191]))
    bus.inject("1/5/9", "write", bytes([170, 128, 0]))
    assert dev.state_snapshot()["on"] is False
    assert _sent(bus)["1/5/2"] == 0 and _sent(bus)["1/5/4"] == bytes([0])
    bus.inject("1/5/1", "write", 1)
    assert dev.state_snapshot()["on"] is True
    assert _sent(bus)["1/5/10"] == bytes([170, 128, 191]) and _sent(bus)["1/5/4"] == bytes([191])


def test_off_reports_value_zero_and_keeps_the_color():
    dev, bus, _ = _setup()
    bus.inject("1/5/9", "write", bytes([85, 255, 255]))
    bus.inject("1/5/1", "write", 0)
    assert _sent(bus)["1/5/10"] == bytes([85, 255, 0])
    assert dev.state_snapshot()["hue"] == pytest.approx(120, abs=0.1)


def test_on_without_an_earlier_brightness_is_full_brightness():
    dev, bus, _ = _setup(Level="0")
    bus.inject("1/5/1", "write", 1)
    assert dev.state_snapshot()["level"] == 100.0
    assert _sent(bus)["1/5/10"][2] == 255


def test_brightness_write_switches_on_and_moves_the_hsv_value():
    dev, bus, _ = _setup(Level="0", Hue="240", Saturation="50")
    bus.inject("1/5/3", "write", bytes([128]))
    assert dev.state_snapshot()["on"] is True
    assert _sent(bus)["1/5/10"] == bytes([170, 128, 128])


def test_only_changed_statuses_and_the_echo_are_sent():
    dev, bus, _ = _setup(Level="60")
    bus.wire.clear()
    bus.inject("1/5/1", "write", 1)                            # already on: only the echo
    assert bus.wire == [("1/5/2", 1)]


# --- start-up, reads, panel ----------------------------------------------------
def test_initial_values_are_broadcast_and_answer_a_read():
    dev, bus, _ = _setup(Level="60", Kelvin="3200", Hue="200", Saturation="60")
    dev.publish_all_status()
    assert _sent(bus) == {"1/5/2": 1, "1/5/4": bytes([153]), "1/5/6": (3200).to_bytes(2, "big"),
                          "1/5/8": bytes([34]), "1/5/10": bytes([142, 153, 153])}
    bus.inject("1/5/10", "read", None)
    bus.inject("1/5/6", "read", None)
    assert bus.wire_responses == [("1/5/10", bytes([142, 153, 153])), ("1/5/6", (3200).to_bytes(2, "big"))]


def test_defaults_are_off_at_the_warm_end_and_red():
    dev, _, _ = _setup()
    assert dev.state_snapshot() == {"on": False, "level": 0.0, "kelvin": 2700, "hue": 0.0, "saturation": 0.0}


def test_panel_commands_publish_what_changed():
    dev, bus, control = _setup(Level="60")
    bus.wire.clear()
    assert control.execute(Command("lamp", "set_kelvin", {"kelvin": 5000})).state["kelvin"] == 5000
    assert {ga for ga, _ in bus.wire} == {"1/5/6", "1/5/8"}
    bus.wire.clear()
    assert control.execute(Command("lamp", "set_kelvin", {"kelvin": 5000})).ok
    assert bus.wire == []
    state = control.execute(Command("lamp", "set_hsv", {"hue": 120, "saturation": 100, "level": 50})).state
    assert state["hue"] == 120 and state["saturation"] == 100 and state["level"] == 50
    assert _sent(bus)["1/5/10"] == bytes([85, 255, 128])
    assert control.execute(Command("lamp", "set_level", {"level": 30})).state["level"] == 30
    assert control.execute(Command("lamp", "set", {"on": False})).state["on"] is False
    assert control.execute(Command("lamp", "toggle", {})).state == {
        "on": True, "level": 30.0, "kelvin": 5000, "hue": 120.0, "saturation": 100.0}


@pytest.mark.parametrize("command,args", [
    ("set_kelvin", {"kelvin": 2000}), ("set_kelvin", {"kelvin": 7000}),
    ("set_hsv", {"hue": 361, "saturation": 50, "level": 50}),
    ("set_hsv", {"hue": 10, "saturation": 101, "level": 50}),
    ("set_hsv", {"hue": 10, "saturation": 50, "level": -1}),
    ("set_level", {"level": 101}),
])
def test_panel_values_outside_their_range_are_refused(command, args):
    dev, bus, control = _setup()
    before = dev.state_snapshot()
    assert not control.execute(Command("lamp", command, args)).ok
    assert dev.state_snapshot() == before


@pytest.mark.parametrize("extra", [{"WarmKelvin": "6500", "ColdKelvin": "2700"},
                                   {"Kelvin": "2000"}, {"Hue": "400"}, {"Saturation": "-5"}, {"Level": "120"}])
def test_invalid_settings_are_refused(extra):
    with pytest.raises(InvalidValueError):
        _setup(**extra)
