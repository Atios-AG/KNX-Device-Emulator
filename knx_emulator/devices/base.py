"""Base contracts for virtual KNX devices."""

from __future__ import annotations

import logging
from abc import ABC
from typing import Any

from knx_emulator.config import AccessoryConfig, CharacteristicConfig
from knx_emulator.knx.bus import KnxBus
from knx_emulator.runtime.state import StateStore

logger = logging.getLogger(__name__)


class VirtualDevice(ABC):
    """Base class for virtual devices exposed on the KNX bus."""

    type_ids: set[int] = set()

    def __init__(
        self,
        config: AccessoryConfig,
        bus: KnxBus,
        state: StateStore,
    ) -> None:
        self.config = config
        self.bus = bus
        self.state = state

    async def start(self) -> None:
        """Start device background tasks."""
        logger.info(
            "Starting virtual device name=%r type=%s id=%s class=%s",
            self.config.name,
            self.config.type_id,
            self.config.id,
            type(self).__name__,
        )

    async def stop(self) -> None:
        """Stop device background tasks."""
        logger.info(
            "Stopping virtual device name=%r type=%s id=%s",
            self.config.name,
            self.config.type_id,
            self.config.id,
        )

    async def on_group_write(
        self,
        characteristic: CharacteristicConfig,
        value: Any,
    ) -> None:
        """Handle a GroupValueWrite addressed to a control address."""

    async def on_local_update(
        self,
        characteristic: CharacteristicConfig,
        value: Any,
    ) -> None:
        """Handle a local state change initiated through the control interface."""
        logger.info(
            "%s local UPDATE characteristic=%s dpt=%s value=%r",
            self.config.name,
            characteristic.name,
            characteristic.dpt,
            value,
        )
        self.state.set(self.config.id, characteristic.name, value)
        await self.publish_state(characteristic)

    async def on_group_read(
        self,
        characteristic: CharacteristicConfig,
        address: str,
    ) -> None:
        """Handle a GroupValueRead addressed to a group address."""
        value = self.state.get(self.config.id, characteristic.name)
        if value is not None:
            logger.info(
                "%s received READ address=%s characteristic=%s dpt=%s -> "
                "respond value=%r",
                self.config.name,
                address,
                characteristic.name,
                characteristic.dpt,
                value,
            )
            await self.bus.response(address, characteristic.dpt, value)
        else:
            logger.warning(
                "%s received READ address=%s characteristic=%s dpt=%s but "
                "state is unknown; no response sent",
                self.config.name,
                address,
                characteristic.name,
                characteristic.dpt,
            )

    async def publish_state(self, characteristic: CharacteristicConfig) -> None:
        """Publish a characteristic state to its status group address."""
        value = self.state.get(self.config.id, characteristic.name)
        if value is not None and characteristic.status_address is not None:
            logger.info(
                "%s publish STATUS address=%s characteristic=%s dpt=%s value=%r",
                self.config.name,
                characteristic.status_address,
                characteristic.name,
                characteristic.dpt,
                value,
            )
            await self.bus.write(
                characteristic.status_address,
                characteristic.dpt,
                value,
            )
        elif characteristic.status_address is None:
            logger.debug(
                "%s not publishing characteristic=%s because it has no "
                "status address",
                self.config.name,
                characteristic.name,
            )
        else:
            logger.warning(
                "%s not publishing characteristic=%s because state is unknown",
                self.config.name,
                characteristic.name,
            )
