"""Fallback virtual device implementation."""

from __future__ import annotations

import logging
from typing import Any

from knx_emulator.config import CharacteristicConfig
from knx_emulator.knx.codec import UnsupportedDPTError, default_value_for_dpt

from .base import VirtualDevice

logger = logging.getLogger(__name__)


class GenericDevice(VirtualDevice):
    """Fallback device for unsupported accessory types."""

    async def start(self) -> None:
        """Initialize readable states so GroupValueRead can be answered."""
        await super().start()
        for characteristic in self.config.characteristics:
            if self.state.has(self.config.id, characteristic.name):
                continue
            try:
                value = default_value_for_dpt(characteristic.dpt)
            except UnsupportedDPTError:
                logger.warning(
                    "%s cannot initialize characteristic=%s dpt=%s: "
                    "unsupported DPT",
                    self.config.name,
                    characteristic.name,
                    characteristic.dpt,
                )
                continue
            self.state.set(self.config.id, characteristic.name, value)
            logger.info(
                "%s initialized characteristic=%s dpt=%s value=%r",
                self.config.name,
                characteristic.name,
                characteristic.dpt,
                value,
            )

    async def on_group_write(
        self,
        characteristic: CharacteristicConfig,
        value: Any,
    ) -> None:
        """Store the written value and publish the matching status when present."""
        logger.info(
            "%s received WRITE characteristic=%s control=%s dpt=%s value=%r "
            "-> store and publish matching status",
            self.config.name,
            characteristic.name,
            characteristic.control_address,
            characteristic.dpt,
            value,
        )
        self.state.set(self.config.id, characteristic.name, value)
        await self.publish_state(characteristic)
