"""Реальная шина поверх xknx (KNXnet/IP).

Единственная точка контакта проекта с внешней библиотекой и сетью. Импорт
xknx ленивый (внутри методов), поэтому остальное ядро и тесты не требуют
установленного xknx.

Подключение задаётся секцией [knx]:
    connection   = tunneling | routing
    gateway_ip   = 192.168.1.10      (для tunneling)
    gateway_port = 3671
    local_ip     = 192.168.1.50      (опционально)
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

    # --- подключение ---------------------------------------------------------
    async def connect(self) -> None:
        try:
            from xknx import XKNX
            from xknx.io import ConnectionConfig, ConnectionType
        except ImportError as exc:  # pragma: no cover
            raise BusError(
                "Не установлен xknx. Установите: pip install xknx"
            ) from exc

        mode = self._config.get("connection", "tunneling").lower()
        if mode == "routing":
            conn = ConnectionConfig(connection_type=ConnectionType.ROUTING)
        else:
            gateway_ip = self._config.get("gateway_ip")
            if not gateway_ip:
                raise BusError("Для tunneling требуется gateway_ip в [knx]")
            # route_back=True заставляет шлюз слать ответы/подтверждения
            # на адрес:порт источника запроса вместо анонсированного HPAI —
            # помогает при NAT и неверно определённом local_ip
            # (симптом: 'L_DATA_CON ... confirmation timed out').
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
        # регистрируем callback приёма до старта (проверенный паттерн)
        self._cb_handle = self._xknx.telegram_queue.register_telegram_received_cb(
            self._on_xknx_telegram
        )
        await self._xknx.start()
        log.info("Подключено к шине KNX (%s)", mode)

    async def disconnect(self) -> None:
        if self._xknx is not None:
            if self._cb_handle is not None:
                self._xknx.telegram_queue.unregister_telegram_received_cb(
                    self._cb_handle
                )
                self._cb_handle = None
            await self._xknx.stop()
            log.info("Отключено от шины KNX")

    # --- приём ---------------------------------------------------------------
    def _on_xknx_telegram(self, telegram) -> None:
        # xknx вызывает этот callback СИНХРОННО (без await), поэтому он не
        # должен быть корутиной. Обработка тоже синхронна; отправка ответов
        # планируется через schedule_* (asyncio.create_task внутри loop).
        from xknx.dpt import DPTArray, DPTBinary
        from xknx.telegram import GroupAddress as XGroupAddress
        from xknx.telegram import TelegramDirection
        from xknx.telegram.apci import GroupValueRead, GroupValueResponse, GroupValueWrite

        if self._handler is None:
            return
        # xknx зовёт callback и на исходящие телеграммы тоже — обрабатываем
        # только входящие, чтобы не реагировать на собственные отправки.
        if telegram.direction is not TelegramDirection.INCOMING:
            return
        # игнорируем внутренние/индивидуальные адреса — только групповые
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

    # --- отправка ------------------------------------------------------------
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

    # --- синхронные обёртки для колбэков устройств ---------------------------
    def schedule_write(self, ga: GroupAddress, dpt: DPT, value) -> None:
        asyncio.create_task(self.send_write(ga, dpt, value))

    def schedule_response(self, ga: GroupAddress, dpt: DPT, value) -> None:
        asyncio.create_task(self.send_response(ga, dpt, value))
