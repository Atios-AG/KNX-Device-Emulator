"""BaseDevice — the contract that every device plugin implements.

Life cycle:
  __init__  -> the manager creates the instance (name, config, bus)
  setup()   -> the plugin declares Action/Status points and reads its parameters
  start()   -> (opt.) start background tasks (timers, cyclic sending)
  ...work...
  stop()    -> (opt.) stop background tasks

Local commands ("as if the state had been changed from a panel") are declared
with the @local_command decorator right in the plugin file. The core invokes
them through a single dispatch_local_command method — the handling itself is
described inside the device.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .datapoint import DataPoint, Direction, StatusPoint
from .exceptions import CommandArgumentError, UnknownCommandError

if TYPE_CHECKING:
    from .bus import BusAdapter
    from .config_loader import DeviceConfig


@dataclass
class CommandSpec:
    name: str
    description: str = ""
    args_schema: dict = field(default_factory=dict)  # {name: type}
    method_name: str = ""


def local_command(name: str, description: str = "", args_schema: dict | None = None):
    """Marks a device method as a local command handler."""

    def decorator(func):
        func._command_spec = CommandSpec(
            name=name, description=description, args_schema=args_schema or {}
        )
        return func

    return decorator


_COERCERS = {
    bool: lambda v: v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "on", "yes"),
    int: lambda v: int(v),
    float: lambda v: float(v),
    str: lambda v: str(v),
}


class BaseDevice(ABC):
    #: binds the plugin to a config section (type = ...); set in the subclass
    TYPE: str = ""

    #: {command name: CommandSpec} — collected automatically from @local_command
    _local_commands: dict[str, CommandSpec] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        commands: dict[str, CommandSpec] = {}
        # inherit the parents' commands, then add our own
        for base in reversed(cls.__mro__[1:]):
            commands.update(getattr(base, "_local_commands", {}) or {})
        for attr_name, attr in vars(cls).items():
            spec = getattr(attr, "_command_spec", None)
            if spec is not None:
                spec.method_name = attr_name
                commands[spec.name] = spec
        cls._local_commands = commands

    def __init__(self, name: str, config: "DeviceConfig", bus: "BusAdapter"):
        self.name = name
        self.config = config
        self._bus = bus
        self.datapoints: list[DataPoint] = []
        #: the device's own logger (named knxsim.device.<name>)
        self.log = logging.getLogger(f"knxsim.device.{name}")

    # --- API for plugins -----------------------------------------------------
    @abstractmethod
    def setup(self) -> None:
        """Declare the data points and read the specific parameters."""

    def add(self, point: DataPoint) -> DataPoint:
        """Register a data point (returns it back for convenience)."""
        point.device = self  # back-reference for logging
        self.datapoints.append(point)
        return point

    def publish_all_status(self) -> None:
        """Broadcast all the Status points to the bus.

        Called at start-up (initial state on power-up) so that the consumers on
        the bus learn the current state right away, without waiting for a Read
        or a command.
        """
        statuses = [dp for dp in self.datapoints if isinstance(dp, StatusPoint)]
        if statuses:
            self.log.info("initial status broadcast (%d item(s))", len(statuses))
        for dp in statuses:
            self.publish(dp)

    def publish(self, point: StatusPoint) -> None:
        """Broadcast the current Status value to the bus (like a real device)."""
        old = point.value
        new = point.read()  # updates point.value
        if old != new:
            self.log.info(
                "state changed: '%s' (%s) %r -> %r — broadcasting to the bus",
                point.name, point.ga, old, new,
            )
        else:
            self.log.debug(
                "status '%s' (%s) = %r (unchanged) — broadcasting to the bus",
                point.name, point.ga, new,
            )
        self._bus.schedule_write(point.ga, point.dpt, new)

    # --- life-cycle hooks (for devices with timers) --------------------------
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    # --- local commands ------------------------------------------------------
    def available_commands(self) -> list[CommandSpec]:
        return list(self._local_commands.values())

    def supports_command(self, name: str) -> bool:
        return name in self._local_commands

    def dispatch_local_command(self, name: str, args: dict | None = None) -> dict:
        spec = self._local_commands.get(name)
        if spec is None:
            raise UnknownCommandError(
                f"Device '{self.name}' does not support the command '{name}'"
            )
        args = dict(args or {})
        kwargs = self._coerce_args(spec, args)
        self.log.info("panel -> local command '%s' %s", name, kwargs or "")
        handler = getattr(self, spec.method_name)
        result = handler(**kwargs)
        state = result if isinstance(result, dict) else self.state_snapshot()
        self.log.info("command '%s' executed, state: %s", name, state)
        return state

    def _coerce_args(self, spec: CommandSpec, args: dict) -> dict:
        kwargs = {}
        for key, typ in spec.args_schema.items():
            if key not in args:
                raise CommandArgumentError(
                    f"Command '{spec.name}': missing argument '{key}'"
                )
            coercer = _COERCERS.get(typ, lambda v: v)
            try:
                kwargs[key] = coercer(args[key])
            except (TypeError, ValueError) as exc:
                raise CommandArgumentError(
                    f"Command '{spec.name}': argument '{key}' must be {typ.__name__}"
                ) from exc
        return kwargs

    # --- state ---------------------------------------------------------------
    def state_snapshot(self) -> dict:
        """The current state across all the Status points."""
        snapshot = {}
        for dp in self.datapoints:
            if isinstance(dp, StatusPoint) or dp.direction in (
                Direction.OUT,
                Direction.IN_OUT,
            ):
                if isinstance(dp, StatusPoint):
                    snapshot[dp.name] = dp.read()
        return snapshot
