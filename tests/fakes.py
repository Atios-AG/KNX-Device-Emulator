"""Test doubles: a bus without a network."""

from __future__ import annotations

from core.address import GroupAddress
from core.bus import BusAdapter


class FakeBusAdapter(BusAdapter):
    """Records what was sent and can inject incoming telegrams."""

    def __init__(self):
        self.writes: list[tuple[GroupAddress, object]] = []
        self.responses: list[tuple[GroupAddress, object]] = []
        self._handler = None

    def set_telegram_handler(self, handler):
        self._handler = handler

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def send_write(self, ga, dpt, value):
        self.writes.append((ga, value))

    async def send_response(self, ga, dpt, value):
        self.responses.append((ga, value))

    def schedule_write(self, ga, dpt, value):
        self.writes.append((ga, value))

    def schedule_response(self, ga, dpt, value):
        self.responses.append((ga, value))

    # --- test helpers -------------------------------------------------------
    def inject(self, ga_str: str, kind: str, raw):
        self._handler(GroupAddress.from_string(ga_str), kind, raw)

    def last_write_value(self):
        return self.writes[-1][1]
