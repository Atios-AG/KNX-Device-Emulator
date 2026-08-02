"""Thermostat behaviour: the On/Off<->mode link, the mode mirror, the season."""

import pytest

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.registry import DeviceRegistry
from devices.thermostat import DPT_HEAT_COOL, DPT_HVAC_MODE
from tests.fakes import FakeBusAdapter

_BASE = {
    "type": "thermostat",
    "ActionOnOff": "1/3/1", "StatusOnOff": "2/3/1",
    "ActionSetpoint": "1/3/2", "StatusSetpoint": "2/3/2",
    "StatusCurrent": "2/3/3",
    "ActionMode": "1/3/4", "StatusMode": "2/3/4",
}


def _setup(extra=None):
    data = dict(_BASE)
    if extra:
        data.update(extra)
    cfg = DeviceConfig("th", data)
    reg = DeviceRegistry(); reg.discover("devices")
    bus = FakeBusAdapter()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[DeviceEntry("th", "thermostat", cfg)]))
    return mgr.get_device("th"), bus, ControlInterface(mgr)


def test_dpt_mode_roundtrip():
    for m in ("off", "heat", "cool", "auto"):
        assert DPT_HVAC_MODE.decode(DPT_HVAC_MODE.encode(m)) == m


def test_dpt_mode_auto_is_option_4():
    assert DPT_HVAC_MODE.encode("auto") == bytes([4])
    assert DPT_HVAC_MODE.decode(bytes([4])) == "auto"


def test_dpt_heatcool_roundtrip():
    assert DPT_HEAT_COOL.decode(DPT_HEAT_COOL.encode("summer")) == "summer"
    assert DPT_HEAT_COOL.decode(DPT_HEAT_COOL.encode("winter")) == "winter"


def test_mode_and_onoff_are_equivalent():
    dev, bus, ctl = _setup()
    # switching on via mode=heat -> on=True, the current mode mirrors it
    s = ctl.execute(Command("th", "set_mode", {"mode": "heat"})).state
    assert s["on"] is True and s["mode"] == "heat"
    # switching off via On/Off=off -> mode=off
    s = ctl.execute(Command("th", "set_onoff", {"on": False})).state
    assert s["on"] is False and s["mode"] == "off"
    # On/Off=on again -> the last active mode is restored (heat)
    s = ctl.execute(Command("th", "set_onoff", {"on": True})).state
    assert s["on"] is True and s["mode"] == "heat"


def test_mode_off_turns_device_off():
    dev, bus, ctl = _setup()
    ctl.execute(Command("th", "set_mode", {"mode": "cool"}))
    s = ctl.execute(Command("th", "set_mode", {"mode": "off"})).state
    assert s["on"] is False and s["mode"] == "off"


def test_bus_write_onoff_and_mode():
    dev, bus, ctl = _setup()
    # Write mode=cool over the bus (raw byte 3 = cool in 20.105)
    bus.inject("1/3/4", "write", bytes([3]))
    assert dev.state_snapshot()["mode"] == "cool"
    assert dev.state_snapshot()["on"] is True
    # Write On/Off=off over the bus
    bus.inject("1/3/1", "write", 0)
    assert dev.state_snapshot()["on"] is False


def test_season_blocks_incompatible_mode():
    dev, bus, ctl = _setup({"StatusSeason": "2/3/5", "Season": "summer"})
    # summer -> heat is unavailable, the command is ignored
    s = ctl.execute(Command("th", "set_mode", {"mode": "heat"})).state
    assert s["mode"] == "off"
    # cool works
    s = ctl.execute(Command("th", "set_mode", {"mode": "cool"})).state
    assert s["mode"] == "cool"


def test_changing_season_turns_off_incompatible_active_mode():
    dev, bus, ctl = _setup({"StatusSeason": "2/3/5", "Season": "winter"})
    ctl.execute(Command("th", "set_mode", {"mode": "heat"}))  # winter, heating
    s = ctl.execute(Command("th", "set_season", {"season": "summer"})).state
    assert s["on"] is False and s["mode"] == "off"
    assert s["season"] == "summer"


def test_season_status_published_on_change():
    dev, bus, ctl = _setup({"StatusSeason": "2/3/5", "Season": "summer"})
    ctl.execute(Command("th", "set_season", {"season": "winter"}))
    season_writes = [(str(g), v) for g, v in bus.writes if str(g) == "2/3/5"]
    assert season_writes, "StatusSeason was not sent on the bus on a season change"
    assert season_writes[-1][1] == "winter"


def test_season_answered_on_read():
    dev, bus, ctl = _setup({"StatusSeason": "2/3/5", "Season": "summer"})
    bus.inject("2/3/5", "read", None)
    answered = [v for g, v in bus.responses if str(g) == "2/3/5"]
    assert answered == ["summer"]


def test_season_disabled_rejects_command():
    dev, bus, ctl = _setup()  # without StatusSeason
    res = ctl.execute(Command("th", "set_season", {"season": "summer"}))
    assert not res.ok
    assert "season" not in dev.state_snapshot()


def test_setpoint_status_published():
    dev, bus, ctl = _setup()
    ctl.execute(Command("th", "set_setpoint", {"value": 23.5}))
    assert dev.state_snapshot()["setpoint"] == pytest.approx(23.5, abs=0.1)


# --- AUTO ------------------------------------------------------------------

def _auto_dev(setpoint=21.0, current=21.0, extra=None):
    cfg = {"Setpoint": str(setpoint), "Current": str(current)}
    cfg.update(extra or {})
    return _setup(cfg)


def test_auto_turns_device_on_and_mirrors_mode():
    dev, bus, ctl = _auto_dev()
    s = ctl.execute(Command("th", "set_mode", {"mode": "auto"})).state
    assert s["on"] is True and s["mode"] == "auto"
    # it is exactly auto (option 4) that goes on the bus, not the chosen direction
    mode_writes = [v for g, v in bus.writes if str(g) == "2/3/4"]
    assert mode_writes[-1] == "auto"


def test_auto_chooses_heat_when_too_cold():
    dev, bus, ctl = _auto_dev(setpoint=22.0, current=19.0)
    s = ctl.execute(Command("th", "set_mode", {"mode": "auto"})).state
    assert s["auto_action"] == "heat"
    dev._tick()
    assert dev.state_snapshot()["current"] == pytest.approx(19.5, abs=0.01)


def test_auto_chooses_cool_when_too_warm():
    dev, bus, ctl = _auto_dev(setpoint=22.0, current=26.0)
    ctl.execute(Command("th", "set_mode", {"mode": "auto"}))
    assert dev.state_snapshot()["auto_action"] == "cool"
    dev._tick()
    assert dev.state_snapshot()["current"] == pytest.approx(25.5, abs=0.01)


def test_auto_idles_inside_hysteresis():
    dev, bus, ctl = _auto_dev(setpoint=21.0, current=21.2)  # |Δ| < 0.5
    s = ctl.execute(Command("th", "set_mode", {"mode": "auto"})).state
    assert s["auto_action"] is None
    dev._tick()
    assert dev.state_snapshot()["current"] == pytest.approx(21.2, abs=0.01)


def test_auto_reacts_to_current_temperature_change():
    dev, bus, ctl = _auto_dev(setpoint=21.0, current=21.0)
    ctl.execute(Command("th", "set_mode", {"mode": "auto"}))
    s = ctl.execute(Command("th", "set_current", {"value": 27.0})).state
    assert s["auto_action"] == "cool"
    s = ctl.execute(Command("th", "set_current", {"value": 15.0})).state
    assert s["auto_action"] == "heat"


def test_auto_reacts_to_setpoint_change():
    dev, bus, ctl = _auto_dev(setpoint=21.0, current=21.0)
    ctl.execute(Command("th", "set_mode", {"mode": "auto"}))
    s = ctl.execute(Command("th", "set_setpoint", {"value": 26.0})).state
    assert s["auto_action"] == "heat"


def test_auto_keeps_heating_until_setpoint():
    dev, bus, ctl = _auto_dev(setpoint=21.0, current=19.0)
    ctl.execute(Command("th", "set_mode", {"mode": "auto"}))
    for _ in range(3):
        dev._tick()
    # 20.5 is already inside the dead band, but the heating that started is not abandoned
    assert dev.state_snapshot()["auto_action"] == "heat"
    dev._tick()
    assert dev.state_snapshot()["current"] == pytest.approx(21.0, abs=0.01)
    assert dev.state_snapshot()["auto_action"] is None  # the target is reached — idle


def test_auto_custom_hysteresis():
    dev, bus, ctl = _auto_dev(setpoint=21.0, current=22.0, extra={"AutoHysteresis": "2.0"})
    s = ctl.execute(Command("th", "set_mode", {"mode": "auto"})).state
    assert s["auto_action"] is None


def test_auto_from_bus():
    dev, bus, ctl = _auto_dev(setpoint=21.0, current=25.0)
    bus.inject("1/3/4", "write", bytes([4]))  # option 4 = auto
    s = dev.state_snapshot()
    assert s["on"] is True and s["mode"] == "auto" and s["auto_action"] == "cool"


def test_auto_restored_by_onoff():
    dev, bus, ctl = _auto_dev()
    ctl.execute(Command("th", "set_mode", {"mode": "auto"}))
    s = ctl.execute(Command("th", "set_onoff", {"on": False})).state
    assert s["mode"] == "off" and "auto_action" not in s
    s = ctl.execute(Command("th", "set_onoff", {"on": True})).state
    assert s["mode"] == "auto"


def test_auto_rejected_when_season_enabled():
    dev, bus, ctl = _auto_dev(extra={"StatusSeason": "2/3/5", "Season": "winter"})
    s = ctl.execute(Command("th", "set_mode", {"mode": "auto"})).state
    assert s["mode"] == "off" and s["on"] is False
    # the same from the bus
    bus.inject("1/3/4", "write", bytes([4]))
    assert dev.state_snapshot()["mode"] == "off"
    # while heat in winter still works
    s = ctl.execute(Command("th", "set_mode", {"mode": "heat"})).state
    assert s["mode"] == "heat"


def test_auto_in_config_ignored_when_season_enabled():
    dev, bus, ctl = _auto_dev(extra={"Mode": "auto", "StatusSeason": "2/3/5", "Season": "summer"})
    assert dev.state_snapshot()["mode"] == "off"


def test_auto_in_config_starts_active():
    dev, bus, ctl = _auto_dev(setpoint=21.0, current=18.0, extra={"Mode": "auto"})
    s = dev.state_snapshot()
    assert s["mode"] == "auto" and s["on"] is True and s["auto_action"] == "heat"
