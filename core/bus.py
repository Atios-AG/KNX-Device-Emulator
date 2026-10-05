"""KNX bus abstraction.

The core and the devices work only with this interface and don't know which
stack is underneath (xknx). The real implementation lives in bus_adapter.py; the
tests use FakeBusAdapter. This makes it possible to test all the logic without
a network.

Incoming telegrams are delivered to the handler in a normalized form:
    handler(ga: GroupAddress, kind: str, raw)
where kind in {"write", "read", "response"}, and raw is an int (binary) or
bytes (array), or None for a plain Read.
"""

from __future__ import annotations

from typing import Callable, Optional

from .address import GroupAddress
from .dpt import DPT

TelegramHandler = Callable[[GroupAddress, str, object], None]


class BusAdapter:
    """Bus contract. Concrete implementations override the methods."""

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

    # Synchronous wrappers for calls from device callbacks (sync context).
    # The real bus schedules a task on the event loop, the fake writes
    # synchronously.
    def schedule_write(self, ga: GroupAddress, dpt: DPT, value) -> None:
        raise NotImplementedError

    def schedule_response(self, ga: GroupAddress, dpt: DPT, value) -> None:
        raise NotImplementedError
