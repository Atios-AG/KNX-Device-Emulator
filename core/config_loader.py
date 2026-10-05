"""Loads and validates the ini configuration.

Reserved sections:
  [knx]      — bus connection parameters (KNXnet/IP)
  [control]  — control interface parameters
All the other sections describe virtual devices; every one of them must have a
type key that binds it to a plugin.
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
    """Type-safe wrapper around a device config section."""

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
                f"[{self.section_name}]: required parameter '{key}' is not set"
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
            f"[{self.section_name}] {key}: expected a boolean, got '{raw}'"
        )

    def get_int(self, key: str, default: int | None = None) -> int | None:
        if key.lower() not in self._data:
            return default
        try:
            return int(self._data[key.lower()])
        except ValueError as exc:
            raise InvalidValueError(
                f"[{self.section_name}] {key}: expected an integer"
            ) from exc

    def get_float(self, key: str, default: float | None = None) -> float | None:
        if key.lower() not in self._data:
            return default
        try:
            return float(self._data[key.lower()])
        except ValueError as exc:
            raise InvalidValueError(
                f"[{self.section_name}] {key}: expected a number"
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
        # no interpolation: '%' is common in comments ("0..100 %") and in
        # values; inline comments after ';' or '#' are stripped, as in the
        # examples of every device plugin
        parser = configparser.ConfigParser(
            interpolation=None, inline_comment_prefixes=(";", "#")
        )
        read = parser.read(path)
        if not read:
            raise ConfigError(f"Configuration file not found: {path}")

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
                    f"[{section}]: device 'type' is not specified"
                )
            devices.append(DeviceEntry(name=section, type=dev_type, config=cfg))

        if not devices:
            raise ConfigError("No devices are described in the config")

        return AppConfig(knx=knx, control=control, devices=devices)
