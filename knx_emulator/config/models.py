"""Internal configuration models shared by all config sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParameterConfig:
    """Normalized accessory parameter."""

    name: str
    value: Any
    display_name: str | None = None
    type_id: int | None = None
    selection: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CharacteristicConfig:
    """Normalized KNX characteristic from any supported config source."""

    name: str
    dpt: str
    control_address: str | None = None
    status_address: str | None = None
    permissions: frozenset[str] = frozenset()
    display: str | None = None
    alias: str | None = None
    required: bool = False
    status_required: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def addresses(self) -> tuple[str, ...]:
        """Return all configured group addresses for this characteristic."""
        return tuple(
            address
            for address in (self.control_address, self.status_address)
            if address
        )


@dataclass(frozen=True)
class AccessoryConfig:
    """Normalized virtual device/accessory configuration."""

    id: str
    name: str
    type_id: int
    characteristics: tuple[CharacteristicConfig, ...]
    parameters: tuple[ParameterConfig, ...] = ()
    version: int | None = None
    timestamp: int | None = None
    disabled: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        """Return True when the accessory should be instantiated."""
        return not self.disabled


@dataclass(frozen=True)
class EmulatorConfig:
    """Configuration consumed by the emulator runtime."""

    accessories: tuple[AccessoryConfig, ...]
    source_format: str
    source_path: str | None = None
    version: int | None = None
    board_type: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)
