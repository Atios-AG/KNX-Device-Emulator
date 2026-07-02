"""Абстракция шины KNX.

Ядро и устройства работают только с этим интерфейсом и ничего не знают про
конкретный стек (xknx). Реальная реализация — в bus_adapter.py, в тестах
используется FakeBusAdapter. Это позволяет тестировать всю логику без сети.

Входящие телеграммы доставляются обработчику в нормализованном виде:
    handler(ga: GroupAddress, kind: str, raw)
где kind ∈ {"write", "read", "response"}, а raw — int (binary) либо bytes
(array), либо None для чистого Read.
"""

from __future__ import annotations

from typing import Callable, Optional

from .address import GroupAddress
from .dpt import DPT

TelegramHandler = Callable[[GroupAddress, str, object], None]


class BusAdapter:
    """Контракт шины. Конкретные реализации переопределяют методы."""

    def set_telegram_handler(self, handler: TelegramHandler) -> None:
        raise NotImplementedError

    async def connect(self) -> None:
        raise NotImplementedError

    async def disconnect(self) -> None:
        raise NotImplementedError

    async def send_write(self, ga: GroupAddress, dpt: DPT, value) -> None:
        raise NotImplementedError

    async def send_response(self, ga: GroupAddress, dpt: DPT, value) -> None:
        raise NotImplementedError

    # Синхронные обёртки для вызова из колбэков устройств (sync-контекст).
    # Реальная шина планирует задачу в event loop, фейк — пишет синхронно.
    def schedule_write(self, ga: GroupAddress, dpt: DPT, value) -> None:
        raise NotImplementedError

    def schedule_response(self, ga: GroupAddress, dpt: DPT, value) -> None:
        raise NotImplementedError
