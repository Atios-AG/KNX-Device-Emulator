"""Точки данных (group objects) — представление устройства на шине.

DataPoint связывает Group Address, кодек DPT, направление и (для Action)
колбэк-обработчик / (для Status) геттер значения. Хранит последнее значение.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Callable

from .address import GroupAddress
from .dpt import DPT

_log = logging.getLogger("knxsim.device")


class Direction(Enum):
    IN = "in"        # Action: принимает GroupValueWrite
    OUT = "out"      # Status: отвечает на Read и рассылает обновления
    IN_OUT = "inout"


class DataPoint:
    def __init__(self, name: str, ga: GroupAddress, dpt: DPT, direction: Direction):
        self.name = name
        self.ga = ga
        self.dpt = dpt
        self.direction = direction
        self.value = None  # последнее известное значение (кэш)
        self.device = None  # обратная ссылка, проставляется BaseDevice.add()

    @property
    def _log(self):
        return self.device.log if self.device is not None else _log

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name} {self.ga} {self.dpt.dpt_id}>"


class ActionPoint(DataPoint):
    """Принимает команды с шины (GroupValueWrite)."""

    def __init__(self, name: str, ga: GroupAddress, dpt: DPT, on_write: Callable):
        super().__init__(name, ga, dpt, Direction.IN)
        self._on_write = on_write

    def handle_write(self, raw) -> None:
        value = self.dpt.decode(raw)
        self.value = value
        self._log.info(
            "KNX → команда на '%s' (%s, DPT %s): значение = %r",
            self.name, self.ga, self.dpt.dpt_id, value,
        )
        self._on_write(value)


class StatusPoint(DataPoint):
    """Отдаёт состояние на шину (Response на Read и рассылка Write)."""

    def __init__(self, name: str, ga: GroupAddress, dpt: DPT, getter: Callable):
        super().__init__(name, ga, dpt, Direction.OUT)
        self._getter = getter

    def read(self):
        self.value = self._getter()
        return self.value
