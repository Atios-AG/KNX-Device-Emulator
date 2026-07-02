"""Загрузка и валидация конфигурации (ini).

Служебные секции:
  [knx]      — параметры подключения к шине (KNXnet/IP)
  [control]  — параметры интерфейса управления
Все остальные секции описывают виртуальные устройства; каждая обязана иметь
ключ type, связывающий её с плагином.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass

from .address import GroupAddress
from .exceptions import (
    ConfigError,
    InvalidValueError,
    MissingOptionError,
)

_RESERVED_SECTIONS = {"knx", "control"}
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class DeviceConfig:
    """Типобезопасная обёртка над секцией конфига устройства."""

    def __init__(self, section_name: str, data: dict[str, str]):
        self.section_name = section_name
        self._data = {k.lower(): v for k, v in data.items()}

    def __contains__(self, key: str) -> bool:
        return key.lower() in self._data

    def get(self, key: str, default=None):
        return self._data.get(key.lower(), default)

    def require(self, key: str) -> str:
        if key.lower() not in self._data:
            raise MissingOptionError(
                f"[{self.section_name}]: обязательный параметр '{key}' не задан"
            )
        return self._data[key.lower()]

    def get_bool(self, key: str, default: bool = False) -> bool:
        if key.lower() not in self._data:
            return default
        raw = self._data[key.lower()].strip().lower()
        if raw in _TRUE:
            return True
        if raw in _FALSE:
            return False
        raise InvalidValueError(
            f"[{self.section_name}] {key}: ожидался boolean, получено '{raw}'"
        )

    def get_int(self, key: str, default: int | None = None) -> int | None:
        if key.lower() not in self._data:
            return default
        try:
            return int(self._data[key.lower()])
        except ValueError as exc:
            raise InvalidValueError(
                f"[{self.section_name}] {key}: ожидалось целое число"
            ) from exc

    def get_ga(self, key: str) -> GroupAddress:
        return GroupAddress.from_string(self.require(key))


@dataclass
class DeviceEntry:
    name: str
    type: str
    config: DeviceConfig


@dataclass
class AppConfig:
    knx: dict[str, str]
    control: dict[str, str]
    devices: list[DeviceEntry]


class ConfigLoader:
    @staticmethod
    def load(path: str) -> AppConfig:
        parser = configparser.ConfigParser()
        read = parser.read(path)
        if not read:
            raise ConfigError(f"Файл конфигурации не найден: {path}")

        knx = dict(parser["knx"]) if parser.has_section("knx") else {}
        control = dict(parser["control"]) if parser.has_section("control") else {}

        devices: list[DeviceEntry] = []
        for section in parser.sections():
            if section.lower() in _RESERVED_SECTIONS:
                continue
            data = dict(parser[section])
            cfg = DeviceConfig(section, data)
            dev_type = cfg.get("type")
            if not dev_type:
                raise MissingOptionError(
                    f"[{section}]: не указан 'type' устройства"
                )
            devices.append(DeviceEntry(name=section, type=dev_type, config=cfg))

        if not devices:
            raise ConfigError("В конфиге не описано ни одного устройства")

        return AppConfig(knx=knx, control=control, devices=devices)
