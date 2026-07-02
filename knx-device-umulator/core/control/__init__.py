"""Интерфейс управления виртуальными устройствами (локальное воздействие)."""

from .command import Command, CommandResult
from .interface import ControlInterface

__all__ = ["Command", "CommandResult", "ControlInterface"]
