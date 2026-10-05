"""Data points (group objects) — the representation of a device on the bus.

A DataPoint binds together a Group Address, a DPT codec, a direction and (for
an Action) a callback handler / (for a Status) a value getter. It keeps the
last known value.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Callable

from .address import GroupAddress
from .dpt import DPT

_log = logging.getLogger("knxsim.device")


class Direction(Enum):
    IN = "in"        # Action: accepts GroupValueWrite
    OUT = "out"      # Status: answers Read and broadcasts updates
    IN_OUT = "inout"


class DataPoint:
    def __init__(self, name: str, ga: GroupAddress, dpt: DPT, direction: Direction):
        self.name = name
        self.ga = ga
        self.dpt = dpt
        self.direction = direction
        self.value = None  # last known value (cache)
        self.device = None  # back-reference, set by BaseDevice.add()

    @property
    def _log(self):
        return self.device.log if self.device is not None else _log

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name} {self.ga} {self.dpt.dpt_id}>"


class ActionPoint(DataPoint):
    """Accepts commands from the bus (GroupValueWrite)."""

    def __init__(self, name: str, ga: GroupAddress, dpt: DPT, on_write: Callable):
        super().__init__(name, ga, dpt, Direction.IN)
        self._on_write = on_write

    def handle_write(self, raw) -> None:
        value = self.dpt.decode(raw)
        self.value = value
        self._log.info(
            "KNX -> command for '%s' (%s, DPT %s): value = %r",
            self.name, self.ga, self.dpt.dpt_id, value,
        )
        self._on_write(value)


class StatusPoint(DataPoint):
    """Publishes state to the bus (Response to a Read and Write broadcasts)."""

    def __init__(self, name: str, ga: GroupAddress, dpt: DPT, getter: Callable):
        super().__init__(name, ga, dpt, Direction.OUT)
        self._getter = getter

    def read(self):
        self.value = self._getter()
        return self.value
