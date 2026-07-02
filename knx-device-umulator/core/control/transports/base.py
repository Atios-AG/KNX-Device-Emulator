"""Базовый класс транспорта управления.

Транспорт доставляет команды снаружи внутрь и зовёт единый
ControlInterface.execute(). Все транспорты взаимозаменяемы; добавить новый
(например, MQTT) — это один файл рядом, по аналогии с плагинами устройств.
"""

from __future__ import annotations

from ..interface import ControlInterface


class ControlTransport:
    #: имя для выбора через [control] transport = ...
    NAME: str = ""

    def __init__(self, interface: ControlInterface, config: dict[str, str]):
        self.interface = interface
        self.config = config
        #: вызывается транспортом, когда он просит завершить приложение
        #: (например, по команде quit). Устанавливается из main.py.
        self.on_stop = None

    def request_stop(self) -> None:
        if self.on_stop is not None:
            self.on_stop()

    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError
