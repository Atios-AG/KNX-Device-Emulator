"""Диспетчер рантайма: связывает конфиг, плагины и шину.

Отвечает за:
  * инстанцирование устройств из конфига и вызов setup();
  * построение таблицы маршрутизации Group Address -> точка данных;
  * доставку входящих телеграмм нужному устройству;
  * доступ к устройствам по имени (для интерфейса управления);
  * запуск/остановку фоновых задач устройств.
"""

from __future__ import annotations

import logging

from .address import GroupAddress
from .bus import BusAdapter
from .config_loader import AppConfig
from .datapoint import ActionPoint, StatusPoint
from .device import BaseDevice
from .exceptions import DuplicateAddressError
from .registry import DeviceRegistry

log = logging.getLogger(__name__)


class DeviceManager:
    def __init__(self, registry: DeviceRegistry, bus: BusAdapter):
        self._registry = registry
        self._bus = bus
        self.devices_by_name: dict[str, BaseDevice] = {}
        self._action_routes: dict[GroupAddress, ActionPoint] = {}
        self._status_routes: dict[GroupAddress, list[StatusPoint]] = {}
        bus.set_telegram_handler(self.on_telegram)

    # --- построение ----------------------------------------------------------
    def build(self, config: AppConfig) -> None:
        for entry in config.devices:
            device = self._registry.create(
                entry.type, entry.name, entry.config, self._bus
            )
            device.setup()
            self.devices_by_name[entry.name] = device
            self._register_routes(device)
            log.info("Создано устройство '%s' (type=%s)", entry.name, entry.type)

    def _register_routes(self, device: BaseDevice) -> None:
        for dp in device.datapoints:
            if isinstance(dp, ActionPoint):
                if dp.ga in self._action_routes:
                    other = self._action_routes[dp.ga]
                    raise DuplicateAddressError(
                        f"Action-адрес {dp.ga} уже занят ({other!r}), "
                        f"конфликт с {dp!r} у '{device.name}'"
                    )
                self._action_routes[dp.ga] = dp
            if isinstance(dp, StatusPoint):
                self._status_routes.setdefault(dp.ga, []).append(dp)

    # --- маршрутизация входящих телеграмм ------------------------------------
    def on_telegram(self, ga: GroupAddress, kind: str, raw) -> None:
        if kind == "write":
            point = self._action_routes.get(ga)
            if point is not None:
                point.handle_write(raw)  # лог пишется внутри handle_write
            else:
                log.debug("WRITE %s — нет устройства на этом адресе, игнор", ga)
        elif kind == "read":
            points = self._status_routes.get(ga, [])
            if not points:
                log.debug("READ %s — нет устройства на этом адресе, игнор", ga)
            for point in points:
                value = point.read()
                point.device.log.info(
                    "KNX → запрос статуса '%s' (%s): отвечаю значением %r",
                    point.name, ga, value,
                )
                self._bus.schedule_response(point.ga, point.dpt, value)
        # kind == "response" игнорируем — мы не опрашиваем чужие статусы

    def get_device(self, name: str) -> BaseDevice | None:
        return self.devices_by_name.get(name)

    # --- жизненный цикл ------------------------------------------------------
    async def start_all(self) -> None:
        for device in self.devices_by_name.values():
            device.publish_all_status()  # начальная рассылка статусов при старте
            await device.start()

    async def stop_all(self) -> None:
        for device in self.devices_by_name.values():
            await device.stop()
