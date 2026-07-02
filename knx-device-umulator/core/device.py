"""BaseDevice — контракт, который реализует каждый плагин устройства.

Жизненный цикл:
  __init__  -> manager создаёт инстанс (имя, конфиг, шина)
  setup()   -> плагин объявляет Action/Status точки и читает свои параметры
  start()   -> (опц.) запуск фоновых задач (таймеры, циклическая отправка)
  ...работа...
  stop()    -> (опц.) остановка фоновых задач

Локальные команды («как будто состояние изменено с панели») объявляются
декоратором @local_command прямо в файле плагина. Ядро вызывает их единым
методом dispatch_local_command — обработка при этом описана внутри устройства.
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
    args_schema: dict = field(default_factory=dict)  # {имя: тип}
    method_name: str = ""


def local_command(name: str, description: str = "", args_schema: dict | None = None):
    """Помечает метод устройства как обработчик локальной команды."""

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
    #: связывает плагин с секцией конфига (type = ...); задаётся в подклассе
    TYPE: str = ""

    #: {имя команды: CommandSpec} — собирается автоматически из @local_command
    _local_commands: dict[str, CommandSpec] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        commands: dict[str, CommandSpec] = {}
        # наследуем команды родителей, затем добавляем свои
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
        #: персональный логгер устройства (имя вида knxsim.device.<name>)
        self.log = logging.getLogger(f"knxsim.device.{name}")

    # --- API для плагинов ----------------------------------------------------
    @abstractmethod
    def setup(self) -> None:
        """Объявить точки данных и прочитать специфичные параметры."""

    def add(self, point: DataPoint) -> DataPoint:
        """Зарегистрировать точку данных (возвращает её же для удобства)."""
        point.device = self  # обратная ссылка для логирования
        self.datapoints.append(point)
        return point

    def publish_all_status(self) -> None:
        """Разослать все Status-точки на шину.

        Вызывается при старте (initial state on power-up), чтобы потребители
        на шине сразу узнали текущее состояние, не дожидаясь Read или команды.
        """
        statuses = [dp for dp in self.datapoints if isinstance(dp, StatusPoint)]
        if statuses:
            self.log.info("начальная рассылка статусов (%d шт.)", len(statuses))
        for dp in statuses:
            self.publish(dp)

    def publish(self, point: StatusPoint) -> None:
        """Разослать текущее значение Status на шину (как реальное устройство)."""
        old = point.value
        new = point.read()  # обновляет point.value
        if old != new:
            self.log.info(
                "состояние изменено: '%s' (%s) %r → %r — рассылаю на шину",
                point.name, point.ga, old, new,
            )
        else:
            self.log.debug(
                "статус '%s' (%s) = %r (без изменений) — рассылаю на шину",
                point.name, point.ga, new,
            )
        self._bus.schedule_write(point.ga, point.dpt, new)

    # --- хуки жизненного цикла (для устройств с таймерами) -------------------
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    # --- локальные команды ---------------------------------------------------
    def available_commands(self) -> list[CommandSpec]:
        return list(self._local_commands.values())

    def supports_command(self, name: str) -> bool:
        return name in self._local_commands

    def dispatch_local_command(self, name: str, args: dict | None = None) -> dict:
        spec = self._local_commands.get(name)
        if spec is None:
            raise UnknownCommandError(
                f"Устройство '{self.name}' не поддерживает команду '{name}'"
            )
        args = dict(args or {})
        kwargs = self._coerce_args(spec, args)
        self.log.info("панель → локальная команда '%s' %s", name, kwargs or "")
        handler = getattr(self, spec.method_name)
        result = handler(**kwargs)
        state = result if isinstance(result, dict) else self.state_snapshot()
        self.log.info("команда '%s' выполнена, состояние: %s", name, state)
        return state

    def _coerce_args(self, spec: CommandSpec, args: dict) -> dict:
        kwargs = {}
        for key, typ in spec.args_schema.items():
            if key not in args:
                raise CommandArgumentError(
                    f"Команда '{spec.name}': пропущен аргумент '{key}'"
                )
            coercer = _COERCERS.get(typ, lambda v: v)
            try:
                kwargs[key] = coercer(args[key])
            except (TypeError, ValueError) as exc:
                raise CommandArgumentError(
                    f"Команда '{spec.name}': аргумент '{key}' должен быть {typ.__name__}"
                ) from exc
        return kwargs

    # --- состояние -----------------------------------------------------------
    def state_snapshot(self) -> dict:
        """Текущее состояние по всем Status-точкам."""
        snapshot = {}
        for dp in self.datapoints:
            if isinstance(dp, StatusPoint) or dp.direction in (
                Direction.OUT,
                Direction.IN_OUT,
            ):
                if isinstance(dp, StatusPoint):
                    snapshot[dp.name] = dp.read()
        return snapshot
