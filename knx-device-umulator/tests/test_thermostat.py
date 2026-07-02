"""Поведение термостата: связь On/Off<->mode, зеркало режима, сезон."""

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
    for m in ("off", "heat", "cool"):
        assert DPT_HVAC_MODE.decode(DPT_HVAC_MODE.encode(m)) == m


def test_dpt_heatcool_roundtrip():
    assert DPT_HEAT_COOL.decode(DPT_HEAT_COOL.encode("summer")) == "summer"
    assert DPT_HEAT_COOL.decode(DPT_HEAT_COOL.encode("winter")) == "winter"


def test_mode_and_onoff_are_equivalent():
    dev, bus, ctl = _setup()
    # включаем через mode=heat -> on=True, current mode зеркалит
    s = ctl.execute(Command("th", "set_mode", {"mode": "heat"})).state
    assert s["on"] is True and s["mode"] == "heat"
    # выключаем через On/Off=off -> mode=off
    s = ctl.execute(Command("th", "set_onoff", {"on": False})).state
    assert s["on"] is False and s["mode"] == "off"
    # снова On/Off=on -> восстанавливается последний активный режим (heat)
    s = ctl.execute(Command("th", "set_onoff", {"on": True})).state
    assert s["on"] is True and s["mode"] == "heat"


def test_mode_off_turns_device_off():
    dev, bus, ctl = _setup()
    ctl.execute(Command("th", "set_mode", {"mode": "cool"}))
    s = ctl.execute(Command("th", "set_mode", {"mode": "off"})).state
    assert s["on"] is False and s["mode"] == "off"


def test_bus_write_onoff_and_mode():
    dev, bus, ctl = _setup()
    # Write mode=cool по шине (raw байт 3 = cool в 20.105)
    bus.inject("1/3/4", "write", bytes([3]))
    assert dev.state_snapshot()["mode"] == "cool"
    assert dev.state_snapshot()["on"] is True
    # Write On/Off=off по шине
    bus.inject("1/3/1", "write", 0)
    assert dev.state_snapshot()["on"] is False


def test_season_blocks_incompatible_mode():
    dev, bus, ctl = _setup({"StatusSeason": "2/3/5", "Season": "summer"})
    # лето -> heat недоступен, команда игнорируется
    s = ctl.execute(Command("th", "set_mode", {"mode": "heat"})).state
    assert s["mode"] == "off"
    # cool работает
    s = ctl.execute(Command("th", "set_mode", {"mode": "cool"})).state
    assert s["mode"] == "cool"


def test_changing_season_turns_off_incompatible_active_mode():
    dev, bus, ctl = _setup({"StatusSeason": "2/3/5", "Season": "winter"})
    ctl.execute(Command("th", "set_mode", {"mode": "heat"}))  # зима, греем
    s = ctl.execute(Command("th", "set_season", {"season": "summer"})).state
    assert s["on"] is False and s["mode"] == "off"
    assert s["season"] == "summer"


def test_season_status_published_on_change():
    dev, bus, ctl = _setup({"StatusSeason": "2/3/5", "Season": "summer"})
    ctl.execute(Command("th", "set_season", {"season": "winter"}))
    season_writes = [(str(g), v) for g, v in bus.writes if str(g) == "2/3/5"]
    assert season_writes, "StatusSeason не отправлен на шину при смене сезона"
    assert season_writes[-1][1] == "winter"


def test_season_answered_on_read():
    dev, bus, ctl = _setup({"StatusSeason": "2/3/5", "Season": "summer"})
    bus.inject("2/3/5", "read", None)
    answered = [v for g, v in bus.responses if str(g) == "2/3/5"]
    assert answered == ["summer"]


def test_season_disabled_rejects_command():
    dev, bus, ctl = _setup()  # без StatusSeason
    res = ctl.execute(Command("th", "set_season", {"season": "summer"}))
    assert not res.ok
    assert "season" not in dev.state_snapshot()


def test_setpoint_status_published():
    dev, bus, ctl = _setup()
    ctl.execute(Command("th", "set_setpoint", {"value": 23.5}))
    assert dev.state_snapshot()["setpoint"] == pytest.approx(23.5, abs=0.1)
