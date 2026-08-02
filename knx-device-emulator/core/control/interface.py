"""ControlInterface — the single entry point for control commands (one for all).

Routes the commands BY DEVICE NAME (unlike the bus, where the addressing is by
Group Address). The command handling itself lives inside the device plugin; the
interface only finds the device, validates the command and wraps the
result/error.
"""

from __future__ import annotations

import logging

from ..exceptions import CommandError, UnknownDeviceError
from .command import Command, CommandResult

log = logging.getLogger(__name__)


class ControlInterface:
    def __init__(self, device_manager):
        self._dm = device_manager

    def execute(self, command: Command) -> CommandResult:
        device = self._dm.get_device(command.device)
        if device is None:
            return CommandResult(
                ok=False,
                device=command.device,
                error=f"There is no device named '{command.device}'",
            )
        try:
            state = device.dispatch_local_command(command.name, command.args)
            log.info(
                "Local command '%s' -> %s: %s",
                command.name, command.device, state,
            )
            return CommandResult(ok=True, device=command.device, state=state)
        except CommandError as exc:
            return CommandResult(ok=False, device=command.device, error=str(exc))

    # --- introspection (for a dynamic panel UI) ------------------------------
    def list_devices(self) -> list[dict]:
        return [
            {
                "name": name,
                "type": device.TYPE,
                "state": device.state_snapshot(),
            }
            for name, device in self._dm.devices_by_name.items()
        ]

    def describe_device(self, name: str) -> dict:
        device = self._dm.get_device(name)
        if device is None:
            raise UnknownDeviceError(f"There is no device named '{name}'")
        return {
            "name": name,
            "type": device.TYPE,
            "state": device.state_snapshot(),
            "commands": [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "args": {k: t.__name__ for k, t in spec.args_schema.items()},
                }
                for spec in device.available_commands()
            ],
        }
