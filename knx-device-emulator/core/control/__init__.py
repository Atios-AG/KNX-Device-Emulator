"""Control interface for the virtual devices (local actuation)."""

from .command import Command, CommandResult
from .interface import ControlInterface

__all__ = ["Command", "CommandResult", "ControlInterface"]
