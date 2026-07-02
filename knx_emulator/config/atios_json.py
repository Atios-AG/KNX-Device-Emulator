"""Atios JSON configuration source."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from knx_emulator.knx.dpt import numeric_dpt_to_str, parse_dpt_from_info

from .models import (
    AccessoryConfig,
    CharacteristicConfig,
    EmulatorConfig,
    ParameterConfig,
)


class AtiosJsonLoader:
    """Load the Atios accessory JSON format."""

    format_name = "atios-json"

    def can_load(self, path: Path) -> bool:
        """Return True for JSON files."""
        return path.suffix.lower() == ".json"

    def load(self, path: Path) -> EmulatorConfig:
        """Load and normalize an Atios JSON file."""
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
        return parse_atios_json(data, source_path=str(path))


def parse_atios_json(
    data: dict[str, Any],
    *,
    source_path: str | None = None,
) -> EmulatorConfig:
    """Normalize an already decoded Atios JSON document."""
    accessories = tuple(
        _parse_accessory(accessory)
        for accessory in data.get("accessories", [])
    )
    return EmulatorConfig(
        accessories=accessories,
        source_format=AtiosJsonLoader.format_name,
        source_path=source_path,
        version=_optional_int(data.get("version")),
        board_type=_optional_int(data.get("board_type")),
        raw=dict(data),
    )


def _parse_accessory(data: dict[str, Any]) -> AccessoryConfig:
    name = str(data.get("name") or "").strip()
    type_id = _optional_int(data.get("type")) or 0
    if not name:
        name = f"[type {type_id}]"

    characteristics = tuple(
        _parse_characteristic(characteristic)
        for characteristic in data.get("characteristics", [])
    )
    parameters = tuple(
        _parse_parameter(parameter)
        for parameter in data.get("parameters", [])
    )

    return AccessoryConfig(
        id=str(data.get("id") or ""),
        name=name,
        type_id=type_id,
        characteristics=characteristics,
        parameters=parameters,
        version=_optional_int(data.get("version")),
        timestamp=_optional_int(data.get("timestamp")),
        disabled=bool(data.get("disabled", False)),
        raw=dict(data),
    )


def _parse_characteristic(data: dict[str, Any]) -> CharacteristicConfig:
    return CharacteristicConfig(
        name=str(data.get("name") or "Unknown"),
        dpt=_parse_dpt(data),
        control_address=_optional_str(data.get("control")),
        status_address=_optional_str(data.get("status")),
        permissions=_parse_permissions(data),
        display=_optional_str(data.get("display")),
        alias=_optional_str(data.get("alias")),
        required=bool(data.get("required", False)),
        status_required=bool(data.get("statusRequired", False)),
        raw=dict(data),
    )


def _parse_parameter(data: dict[str, Any]) -> ParameterConfig:
    return ParameterConfig(
        name=str(data.get("name") or ""),
        value=data.get("value"),
        display_name=_optional_str(data.get("displayName")),
        type_id=_optional_int(data.get("type")),
        selection=tuple(str(item) for item in data.get("selection", [])),
        raw=dict(data),
    )


def _parse_dpt(data: dict[str, Any]) -> str:
    explicit = data.get("dpt")
    if explicit is not None:
        return numeric_dpt_to_str(explicit)

    info = _optional_str(data.get("info"))
    if info:
        parsed = parse_dpt_from_info(info)
        if parsed is not None:
            return parsed

    return "1.001"


def _parse_permissions(data: dict[str, Any]) -> frozenset[str]:
    permissions = data.get("permissions")
    if isinstance(permissions, str):
        return frozenset(permissions)

    permission = data.get("permission")
    if permission is None:
        return frozenset()

    try:
        permission_bits = int(permission)
    except (TypeError, ValueError):
        return frozenset()

    parsed: set[str] = set()
    if permission_bits & 1:
        parsed.add("r")
    if permission_bits & 2:
        parsed.add("w")
    return frozenset(parsed)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
