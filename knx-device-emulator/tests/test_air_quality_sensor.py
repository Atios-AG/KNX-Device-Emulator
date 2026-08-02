"""Behaviour of the air_quality_sensor plugin: sensor set, local set, polling."""

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.dpt import DPT_UCOUNT
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter

# The full set of sensors with all the Group Addresses.
_FULL = {
    "type": "air_quality_sensor",
    "StatusAQI": "3/0/1",
    "StatusCH2O": "3/0/2",
    "StatusTVOC": "3/0/3",
    "StatusPM1": "3/0/4",
    "StatusPM2_5": "3/0/5",
    "StatusPM10": "3/0/6",
    "StatusCO2": "3/0/7",
    "AQI": "50",
    "CO2": "400",
}


def _setup(data=None):
    data = data or dict(_FULL)
    cfg = DeviceConfig("air0", data)
    reg = DeviceRegistry()
    reg.discover("devices")
    bus = FakeBusAdapter()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[
        DeviceEntry("air0", "air_quality_sensor", cfg)
    ]))
    return mgr, bus, ControlInterface(mgr)


def test_initial_state_reflects_config():
    mgr, bus, control = _setup()
    state = control.describe_device("air0")["state"]
    assert state["aqi"] == 50
    assert state["co2"] == 400.0
    assert state["ch2o"] == 0.0  # not set in the config — 0


def test_only_configured_sensors_present():
    mgr, bus, control = _setup({
        "type": "air_quality_sensor",
        "StatusCO2": "3/0/7",  # only CO2 is enabled
        "CO2": "800",
    })
    state = control.describe_device("air0")["state"]
    assert set(state) == {"co2"}
    assert state["co2"] == 800.0


def test_each_sensor_is_its_own_command():
    mgr, bus, control = _setup()
    cmds = {c["name"]: c for c in control.describe_device("air0")["commands"]}
    # one command per configured sensor, the single argument is `set`
    assert set(cmds) == {"aqi", "ch2o", "tvoc", "pm1", "pm2_5", "pm10", "co2"}
    assert cmds["co2"]["args"] == {"set": "float"}


def test_commands_track_configured_sensors():
    mgr, bus, control = _setup({
        "type": "air_quality_sensor",
        "StatusCO2": "3/0/7",
        "StatusAQI": "3/0/1",
    })
    names = {c["name"] for c in control.describe_device("air0")["commands"]}
    assert names == {"co2", "aqi"}


def test_sensor_command_updates_and_emits_on_right_ga():
    mgr, bus, control = _setup()
    res = control.execute(Command("air0", "co2", {"set": 1234}))
    assert res.ok
    assert res.state["co2"] == 1234.0
    # the status went exactly to the CO2 address
    ga, value = bus.writes[-1]
    assert str(ga) == "3/0/7"
    assert value == 1234.0


def test_pm2_5_command():
    mgr, bus, control = _setup()
    res = control.execute(Command("air0", "pm2_5", {"set": 12.4}))
    assert res.ok
    assert res.state["pm2_5"] == 12.4


def test_aqi_is_integer():
    mgr, bus, control = _setup()
    res = control.execute(Command("air0", "aqi", {"set": 199.6}))
    assert res.state["aqi"] == 200  # rounded to an integer


def test_unknown_sensor_command_fails():
    mgr, bus, control = _setup()
    res = control.execute(Command("air0", "radon", {"set": 1}))
    assert not res.ok
    assert "radon" in res.error


def test_read_responds_with_current_value():
    mgr, bus, control = _setup()
    bus.inject("3/0/1", "read", None)  # polling the AQI
    ga, value = bus.responses[-1]
    assert str(ga) == "3/0/1"
    assert value == 50


def test_encoded_aqi_is_single_byte():
    # AQI is encoded with DPT 5.010 — exactly one byte
    assert DPT_UCOUNT.encode(50) == bytes([50])
