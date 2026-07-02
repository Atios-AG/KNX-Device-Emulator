"""CLI/REPL-транспорт управления с TAB-автодополнением.

Использует prompt_toolkit: по нажатию TAB показывает список доступных на
текущем уровне вариантов с описанием справа (display_meta):
  * 1-й уровень — имена устройств + встроенные команды (list/describe/help/quit);
  * 2-й уровень — команды выбранного устройства с описаниями;
  * 3-й уровень — аргументы вида ключ= и подсказки значений (true/false и т.п.).

Формат строки прежний:  <device> <command> [key=value ...]
Если stdin не TTY (ввод из пайпа) — откат на простой построчный ввод.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from ...exceptions import UnknownDeviceError
from ..command import Command
from .base import ControlTransport

log = logging.getLogger(__name__)

_BUILTINS = {
    "list": "показать все устройства и их состояние",
    "describe": "подробно: состояние + доступные команды",
    "help": "справка по CLI",
    "quit": "выход",
}

# Подсказки значений для распространённых аргументов (удобство CLI).
_VALUE_HINTS = {
    "mode": ["off", "heat", "cool"],
    "season": ["summer", "winter"],
    "on": ["true", "false"],
}


def _build_completer(interface):
    from prompt_toolkit.completion import Completer, Completion

    class ControlCompleter(Completer):
        def __init__(self, iface):
            self.iface = iface

        # --- источники данных ----------------------------------------------
        def _devices(self) -> dict[str, str]:
            return {d["name"]: d["type"] for d in self.iface.list_devices()}

        def _commands(self, device: str) -> list[dict]:
            try:
                return self.iface.describe_device(device)["commands"]
            except UnknownDeviceError:
                return []

        # --- основной разбор -----------------------------------------------
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            tokens = text.split()
            ends_with_space = text == "" or text[-1].isspace()
            if ends_with_space:
                word, index = "", len(tokens)
            else:
                word, index = tokens[-1], len(tokens) - 1

            if index == 0:
                yield from self._first_level(word, Completion)
                return

            head = tokens[0]
            if head in _BUILTINS:
                if head == "describe" and index == 1:
                    yield from self._device_names(word, Completion)
                return

            devices = self._devices()
            if head not in devices:
                return
            if index == 1:
                yield from self._command_names(head, word, Completion)
            else:
                yield from self._argument_level(head, tokens, word, index, Completion)

        # --- уровни ---------------------------------------------------------
        def _first_level(self, word, Completion):
            for name, dev_type in self._devices().items():
                if name.startswith(word):
                    yield Completion(name, start_position=-len(word),
                                     display_meta=f"устройство ({dev_type})")
            for name, desc in _BUILTINS.items():
                if name.startswith(word):
                    yield Completion(name, start_position=-len(word), display_meta=desc)

        def _device_names(self, word, Completion):
            for name, dev_type in self._devices().items():
                if name.startswith(word):
                    yield Completion(name, start_position=-len(word),
                                     display_meta=f"устройство ({dev_type})")

        def _command_names(self, device, word, Completion):
            for cmd in self._commands(device):
                if cmd["name"].startswith(word):
                    meta = cmd.get("description") or "команда"
                    yield Completion(cmd["name"], start_position=-len(word), display_meta=meta)

        def _argument_level(self, device, tokens, word, index, Completion):
            cmd_name = tokens[1]
            spec = next((c for c in self._commands(device) if c["name"] == cmd_name), None)
            if spec is None:
                return
            args: dict = spec.get("args", {})

            # дополняем значение: ключ=<...>
            if "=" in word:
                key, _, partial = word.partition("=")
                for value in self._value_candidates(key, args.get(key)):
                    if value.startswith(partial):
                        yield Completion(value, start_position=-len(partial),
                                         display_meta="значение")
                return

            # дополняем имена ещё не введённых аргументов
            already = {t.split("=", 1)[0] for t in tokens[2:index]}
            for name, type_name in args.items():
                if name in already or not name.startswith(word):
                    continue
                yield Completion(name + "=", start_position=-len(word),
                                 display_meta=f"аргумент ({type_name})")

        @staticmethod
        def _value_candidates(key, type_name):
            if key in _VALUE_HINTS:
                return _VALUE_HINTS[key]
            if type_name == "bool":
                return ["true", "false"]
            return []

    return ControlCompleter(interface)


class CliTransport(ControlTransport):
    NAME = "cli"

    def __init__(self, interface, config):
        super().__init__(interface, config)
        self._task = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        log.info("CLI интерфейс управления запущен (TAB — автодополнение, 'help' — справка)")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    # --- цикл ввода ---------------------------------------------------------
    async def _loop(self) -> None:
        if not sys.stdin.isatty():
            await self._loop_plain()
            return
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.patch_stdout import patch_stdout
        except ImportError:
            log.warning("prompt_toolkit не установлен — автодополнение недоступно")
            await self._loop_plain()
            return

        session = PromptSession(
            completer=_build_completer(self.interface),
            complete_while_typing=False,
        )
        with patch_stdout():
            while True:
                try:
                    line = await session.prompt_async("knx> ")
                except (EOFError, KeyboardInterrupt):
                    break
                if self._handle(line.strip()):
                    break
        self.request_stop()

    async def _loop_plain(self) -> None:
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            if self._handle(line.strip()):
                break
        self.request_stop()

    # --- обработка одной строки --------------------------------------------
    def _handle(self, line: str) -> bool:
        """Возвращает True, если нужно завершить работу."""
        if not line:
            return False
        if line in ("quit", "exit"):
            return True
        if line in ("help", "?"):
            print("Формат: <device> <command> [key=value ...]")
            print("Служебные: list | describe <dev> | help | quit")
            print("TAB — показать доступные варианты с описанием")
            return False
        if line == "list":
            for item in self.interface.list_devices():
                print(f"  {item['name']} ({item['type']}): {item['state']}")
            return False
        if line.startswith("describe "):
            name = line.split(None, 1)[1]
            try:
                print(self.interface.describe_device(name))
            except UnknownDeviceError as exc:
                print(f"Ошибка: {exc}")
            return False
        try:
            command = Command.from_line(line)
        except ValueError as exc:
            print(f"Ошибка: {exc}")
            return False
        print(self.interface.execute(command).to_dict())
        return False
