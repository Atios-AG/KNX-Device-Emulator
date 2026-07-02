"""Подробное логирование событий устройства."""

import logging

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.control import Command, ControlInterface
from core.device_manager import DeviceManager
from core.registry import DeviceRegistry
from tests.fakes import FakeBusAdapter


def _setup():
    cfg = DeviceConfig("outlet0", {
        "type": "outlet", "Action": "1/1/1", "Status": "2/2/2",
    })
    reg = DeviceRegistry(); reg.discover("devices")
    bus = FakeBusAdapter()
    mgr = DeviceManager(reg, bus)
    mgr.build(AppConfig(knx={}, control={}, devices=[DeviceEntry("outlet0", "outlet", cfg)]))
    return mgr, bus, ControlInterface(mgr)


def test_incoming_knx_write_logged(caplog):
    mgr, bus, _ = _setup()
    with caplog.at_level(logging.INFO, logger="knxsim.device.outlet0"):
        bus.inject("1/1/1", "write", 1)
    text = caplog.text
    assert "KNX → команда" in text       # факт прихода команды по KNX
    assert "1/1/1" in text               # на какой адрес
    assert "состояние изменено" in text  # что изменилось
    assert "True" in text                # и новое значение


def test_read_request_logged(caplog):
    mgr, bus, _ = _setup()
    with caplog.at_level(logging.INFO, logger="knxsim.device.outlet0"):
        bus.inject("2/2/2", "read", None)
    assert "запрос статуса" in caplog.text


def test_local_command_logged(caplog):
    mgr, bus, ctl = _setup()
    with caplog.at_level(logging.INFO, logger="knxsim.device.outlet0"):
        ctl.execute(Command("outlet0", "toggle"))
    assert "локальная команда 'toggle'" in caplog.text
    assert "выполнена" in caplog.text


def test_per_device_logger_name():
    mgr, _, _ = _setup()
    assert mgr.get_device("outlet0").log.name == "knxsim.device.outlet0"
