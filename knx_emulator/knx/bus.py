"""KNX bus abstraction over xknx."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from xknx import XKNX
from xknx.io import ConnectionConfig, ConnectionType
from xknx.telegram import GroupAddress, Telegram, TelegramDirection
from xknx.telegram.apci import GroupValueRead, GroupValueResponse, GroupValueWrite

from .codec import (
    UnsupportedDPTError,
    decode_payload,
    encode_group_value_response,
    encode_group_value_write,
)

logger = logging.getLogger(__name__)

TelegramKind = Literal["read", "write", "response"]
TelegramCallback = Callable[["BusTelegram"], Awaitable[None] | None]


@dataclass(frozen=True)
class BusTelegram:
    """Normalized incoming KNX group telegram."""

    kind: TelegramKind
    address: str
    dpt: str | None
    value: Any = None
    raw: Telegram | None = None


class KnxBus:
    """Small xknx adapter used by virtual devices and the runtime engine."""

    def __init__(
        self,
        *,
        gateway_ip: str,
        gateway_port: int = 3671,
        connection_type: ConnectionType = ConnectionType.TUNNELING,
    ) -> None:
        self._connection_config = ConnectionConfig(
            connection_type=connection_type,
            gateway_ip=gateway_ip,
            gateway_port=gateway_port,
        )
        self._xknx: XKNX | None = None
        self._callbacks: list[TelegramCallback] = []
        self._address_dpts: dict[str, str] = {}
        self._telegram_callback_handle: Any = None

    async def start(self) -> None:
        """Connect to KNX/IP and start receiving telegrams."""
        if self._xknx is not None:
            return

        logger.info(
            "Connecting to KNX/IP gateway %s:%s",
            self._connection_config.gateway_ip,
            self._connection_config.gateway_port,
        )
        self._xknx = XKNX(connection_config=self._connection_config)
        self._telegram_callback_handle = (
            self._xknx.telegram_queue.register_telegram_received_cb(
                self._on_xknx_telegram
            )
        )
        await self._xknx.start()
        logger.info("Connected to KNX/IP gateway")

    async def stop(self) -> None:
        """Disconnect from KNX/IP."""
        if self._xknx is None:
            return

        logger.info("Disconnecting from KNX/IP gateway")
        if self._telegram_callback_handle is not None:
            self._xknx.telegram_queue.unregister_telegram_received_cb(
                self._telegram_callback_handle
            )
            self._telegram_callback_handle = None

        await self._xknx.stop()
        self._xknx = None
        logger.info("Disconnected from KNX/IP gateway")

    def register_address(self, address: str, dpt: str) -> None:
        """Register the DPT used to decode incoming telegrams for an address."""
        self._address_dpts[address] = dpt
        logger.debug("Registered KNX address=%s dpt=%s", address, dpt)

    def subscribe(self, callback: TelegramCallback) -> None:
        """Subscribe to normalized incoming KNX telegrams."""
        self._callbacks.append(callback)

    def unsubscribe(self, callback: TelegramCallback) -> None:
        """Remove a previously registered subscriber."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    async def write(self, address: str, dpt: str, value: Any) -> None:
        """Send a GroupValueWrite telegram to the KNX bus."""
        logger.info(
            "Sending GroupValueWrite address=%s dpt=%s value=%r",
            address,
            dpt,
            value,
        )
        await self._send(address, encode_group_value_write(dpt, value))

    async def response(self, address: str, dpt: str, value: Any) -> None:
        """Send a GroupValueResponse telegram to the KNX bus."""
        logger.info(
            "Sending GroupValueResponse address=%s dpt=%s value=%r",
            address,
            dpt,
            value,
        )
        await self._send(address, encode_group_value_response(dpt, value))

    async def _send(
        self,
        address: str,
        payload: GroupValueWrite | GroupValueResponse,
    ) -> None:
        if self._xknx is None:
            raise RuntimeError("KNX bus is not started")

        telegram = Telegram(
            destination_address=GroupAddress(address),
            direction=TelegramDirection.OUTGOING,
            payload=payload,
        )
        await self._xknx.telegrams.put(telegram)

    def _on_xknx_telegram(self, telegram: Telegram) -> None:
        if telegram.direction is not TelegramDirection.INCOMING:
            return
        if not isinstance(telegram.destination_address, GroupAddress):
            return

        bus_telegram = self._normalize_telegram(telegram)
        if bus_telegram is None:
            return

        logger.info(
            "Received KNX %s address=%s dpt=%s value=%r raw=%s",
            bus_telegram.kind,
            bus_telegram.address,
            bus_telegram.dpt,
            bus_telegram.value,
            telegram,
        )

        for callback in tuple(self._callbacks):
            try:
                result = callback(bus_telegram)
                if inspect.isawaitable(result):
                    asyncio.create_task(result)
            except Exception:
                logger.exception(
                    "Unexpected error while handling KNX telegram %s",
                    telegram,
                )

    def _normalize_telegram(self, telegram: Telegram) -> BusTelegram | None:
        address = str(telegram.destination_address)
        dpt = self._address_dpts.get(address)
        payload = telegram.payload

        if isinstance(payload, GroupValueRead):
            return BusTelegram(
                kind="read",
                address=address,
                dpt=dpt,
                raw=telegram,
            )

        if isinstance(payload, GroupValueWrite):
            return BusTelegram(
                kind="write",
                address=address,
                dpt=dpt,
                value=self._decode(address, dpt, payload),
                raw=telegram,
            )

        if isinstance(payload, GroupValueResponse):
            return BusTelegram(
                kind="response",
                address=address,
                dpt=dpt,
                value=self._decode(address, dpt, payload),
                raw=telegram,
            )

        return None

    @staticmethod
    def _decode(address: str, dpt: str | None, payload: Any) -> Any:
        if dpt is None:
            logger.warning(
                "Received KNX telegram for unregistered group address %s",
                address,
            )
            return None

        try:
            return decode_payload(dpt, payload)
        except (TypeError, ValueError, UnsupportedDPTError):
            logger.exception(
                "Could not decode KNX telegram for %s with DPT %s",
                address,
                dpt,
            )
            return None
