"""Real bus on top of xknx (KNXnet/IP).

The only point where the project touches an external library and the network.
The xknx import is lazy (inside the methods), so the rest of the core and the
tests do not require xknx to be installed.

The connection is configured by the [knx] section:
    connection   = tunneling | routing
    gateway_ip   = 192.168.1.10      (for tunneling)
    gateway_port = 3671
    local_ip     = 192.168.1.50      (optional)
"""

from __future__ import annotations

import asyncio
import logging

from .address import GroupAddress
from .bus import BusAdapter, TelegramHandler
from .dpt import DPT
from .exceptions import BusError

log = logging.getLogger(__name__)


class KNXIPBusAdapter(BusAdapter):
    def __init__(self, knx_config: dict[str, str]):
        self._config = knx_config
        self._xknx = None
        self._handler: TelegramHandler | None = None
        self._cb_handle = None

    def set_telegram_handler(self, handler: TelegramHandler) -> None:
        self._handler = handler

    # --- connection ----------------------------------------------------------
    async def connect(self) -> None:
        try:
            from xknx import XKNX
            from xknx.io import ConnectionConfig, ConnectionType
        except ImportError as exc:  # pragma: no cover
            raise BusError(
                "xknx is not installed. Install it with: pip install xknx"
            ) from exc

        mode = self._config.get("connection", "tunneling").lower()
        if mode == "routing":
            conn = ConnectionConfig(connection_type=ConnectionType.ROUTING)
        else:
            gateway_ip = self._config.get("gateway_ip")
            if not gateway_ip:
                raise BusError("tunneling requires gateway_ip in [knx]")
            # route_back=True makes the gateway send responses/confirmations to
            # the source address:port of the request instead of the announced
            # HPAI — this helps with NAT and an incorrectly detected local_ip
            # (symptom: 'L_DATA_CON ... confirmation timed out').
            route_back = str(self._config.get("route_back", "")).strip().lower() in (
                "1", "true", "yes", "on"
            )
            conn = ConnectionConfig(
                connection_type=ConnectionType.TUNNELING,
                gateway_ip=gateway_ip,
                gateway_port=int(self._config.get("gateway_port", 3671)),
                local_ip=self._config.get("local_ip"),
                route_back=route_back,
            )

        self._xknx = XKNX(connection_config=conn)
        # register the receive callback before starting xknx
        self._cb_handle = self._xknx.telegram_queue.register_telegram_received_cb(
            self._on_xknx_telegram
        )
        await self._xknx.start()
        log.info("Connected to the KNX bus (%s)", mode)

    async def disconnect(self) -> None:
        if self._xknx is not None:
            if self._cb_handle is not None:
                self._xknx.telegram_queue.unregister_telegram_received_cb(
                    self._cb_handle
                )
                self._cb_handle = None
            await self._xknx.stop()
            log.info("Disconnected from the KNX bus")

    # --- receiving -----------------------------------------------------------
    def _on_xknx_telegram(self, telegram) -> None:
        # xknx invokes this callback SYNCHRONOUSLY (without await), so it must
        # not be a coroutine. The handling is synchronous too; sending the
        # responses is scheduled via schedule_* (asyncio.create_task inside the
        # loop).
        from xknx.dpt import DPTArray, DPTBinary
        from xknx.telegram import GroupAddress as XGroupAddress
        from xknx.telegram import TelegramDirection
        from xknx.telegram.apci import GroupValueRead, GroupValueResponse, GroupValueWrite

        if self._handler is None:
            return
        # xknx calls the callback for outgoing telegrams as well — handle only
        # the incoming ones so we do not react to our own sends.
        if telegram.direction is not TelegramDirection.INCOMING:
            return
        # ignore internal/individual addresses — group addresses only
        if not isinstance(telegram.destination_address, XGroupAddress):
            return
        ga = GroupAddress.from_string(str(telegram.destination_address))
        apci = telegram.payload

        if isinstance(apci, GroupValueRead):
            self._handler(ga, "read", None)
            return

        if isinstance(apci, (GroupValueWrite, GroupValueResponse)):
            kind = "write" if isinstance(apci, GroupValueWrite) else "response"
            value = apci.value
            if isinstance(value, DPTBinary):
                raw = value.value
            elif isinstance(value, DPTArray):
                raw = bytes(value.value)
            else:
                raw = value
            self._handler(ga, kind, raw)

    # --- sending -------------------------------------------------------------
    async def send_write(self, ga: GroupAddress, dpt: DPT, value) -> None:
        await self._send(ga, dpt, value, response=False)

    async def send_response(self, ga: GroupAddress, dpt: DPT, value) -> None:
        await self._send(ga, dpt, value, response=True)

    async def _send(self, ga: GroupAddress, dpt: DPT, value, response: bool) -> None:
        from xknx.dpt import DPTArray, DPTBinary
        from xknx.telegram import Telegram, TelegramDirection
        from xknx.telegram import GroupAddress as XGroupAddress
        from xknx.telegram.apci import GroupValueResponse, GroupValueWrite

        raw = dpt.encode(value)
        payload = DPTBinary(raw) if dpt.payload_kind == "binary" else DPTArray(raw)
        apci_cls = GroupValueResponse if response else GroupValueWrite
        telegram = Telegram(
            destination_address=XGroupAddress(str(ga)),
            direction=TelegramDirection.OUTGOING,
            payload=apci_cls(payload),
        )
        await self._xknx.telegrams.put(telegram)

    # --- synchronous wrappers for device callbacks ---------------------------
    def schedule_write(self, ga: GroupAddress, dpt: DPT, value) -> None:
        asyncio.create_task(self.send_write(ga, dpt, value))

    def schedule_response(self, ga: GroupAddress, dpt: DPT, value) -> None:
        asyncio.create_task(self.send_response(ga, dpt, value))
