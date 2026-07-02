"""Virtual climate and thermostat device implementations."""

from __future__ import annotations

import logging
from typing import Any

from knx_emulator.config import CharacteristicConfig

from .generic import GenericDevice
from .registry import register_device

logger = logging.getLogger(__name__)


@register_device(type_ids={30, 47})
class ClimateDevice(GenericDevice):
    """Virtual thermostat/HVAC device."""

    async def start(self) -> None:
        """Initialize climate state with paired target/current values."""
        await super().start()
        for characteristic in self.config.characteristics:
            if not characteristic.name.startswith("Target"):
                continue
            current_characteristic = self._matching_current_characteristic(
                characteristic
            )
            if current_characteristic is None:
                continue

            target_value = self.state.get(self.config.id, characteristic.name)
            if target_value is None:
                continue

            self.state.set(
                self.config.id,
                current_characteristic.name,
                target_value,
            )
            logger.info(
                "%s initialized paired state %s=%r from %s",
                self.config.name,
                current_characteristic.name,
                target_value,
                characteristic.name,
            )

    async def on_group_write(
        self,
        characteristic: CharacteristicConfig,
        value: Any,
    ) -> None:
        """Handle writable climate characteristics."""
        logger.info(
            "%s interpreted WRITE characteristic=%s control=%s dpt=%s value=%r",
            self.config.name,
            characteristic.name,
            characteristic.control_address,
            characteristic.dpt,
            value,
        )
        self.state.set(self.config.id, characteristic.name, value)

        if characteristic.status_address is not None:
            logger.info(
                "%s maps %s write to same characteristic status address=%s",
                self.config.name,
                characteristic.name,
                characteristic.status_address,
            )
            await self.publish_state(characteristic)
            return

        current_characteristic = self._matching_current_characteristic(characteristic)
        if current_characteristic is not None:
            logger.info(
                "%s maps %s write to paired status characteristic=%s "
                "address=%s",
                self.config.name,
                characteristic.name,
                current_characteristic.name,
                current_characteristic.status_address,
            )
            self.state.set(self.config.id, current_characteristic.name, value)
            await self.publish_state(current_characteristic)
        else:
            logger.info(
                "%s stored %s=%r without publishing a status: no matching "
                "status characteristic",
                self.config.name,
                characteristic.name,
                value,
            )

    async def on_local_update(
        self,
        characteristic: CharacteristicConfig,
        value: Any,
    ) -> None:
        """Handle a local HVAC state change and publish KNX status."""
        logger.info(
            "%s local UPDATE characteristic=%s dpt=%s value=%r",
            self.config.name,
            characteristic.name,
            characteristic.dpt,
            value,
        )
        self.state.set(self.config.id, characteristic.name, value)

        if characteristic.status_address is not None:
            await self.publish_state(characteristic)
            return

        current_characteristic = self._matching_current_characteristic(characteristic)
        if current_characteristic is not None:
            self.state.set(self.config.id, current_characteristic.name, value)
            await self.publish_state(current_characteristic)

    def _matching_current_characteristic(
        self,
        characteristic: CharacteristicConfig,
    ) -> CharacteristicConfig | None:
        if not characteristic.name.startswith("Target"):
            return None

        current_name = "Current" + characteristic.name.removeprefix("Target")
        for candidate in self.config.characteristics:
            if candidate.name == current_name and candidate.status_address is not None:
                return candidate

        return None
