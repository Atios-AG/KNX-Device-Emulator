"""Configuration validation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import EmulatorConfig

_GROUP_ADDRESS_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{1,3}$")
_DPT_RE = re.compile(r"^\d+\.\d+$")


@dataclass(frozen=True)
class ConfigValidationError(ValueError):
    """Raised when a configuration cannot be safely used."""

    errors: tuple[str, ...]

    def __str__(self) -> str:
        return "Invalid configuration:\n" + "\n".join(
            f"- {error}" for error in self.errors
        )


def validate_config(config: EmulatorConfig) -> None:
    """Validate normalized emulator configuration."""
    errors: list[str] = []
    address_owners: dict[str, str] = {}

    for accessory in config.accessories:
        if not accessory.id:
            errors.append(f"{accessory.name}: missing accessory id")
        if accessory.type_id <= 0:
            errors.append(f"{accessory.name}: invalid type id {accessory.type_id!r}")

        for characteristic in accessory.characteristics:
            owner = f"{accessory.name} / {characteristic.name}"

            if not _DPT_RE.match(characteristic.dpt):
                errors.append(f"{owner}: invalid DPT {characteristic.dpt!r}")

            if characteristic.required and not characteristic.control_address:
                errors.append(f"{owner}: required control address is missing")
            if characteristic.status_required and not characteristic.status_address:
                errors.append(f"{owner}: required status address is missing")

            for address in characteristic.addresses:
                if not _GROUP_ADDRESS_RE.match(address):
                    errors.append(f"{owner}: invalid group address {address!r}")
                    continue

                previous_owner = address_owners.get(address)
                if previous_owner is not None:
                    errors.append(
                        f"group address {address} is used by both "
                        f"{previous_owner} and {owner}"
                    )
                else:
                    address_owners[address] = owner

    if errors:
        raise ConfigValidationError(tuple(errors))
