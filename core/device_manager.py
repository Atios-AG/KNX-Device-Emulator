"""Runtime dispatcher: binds together the config, the plugins and the bus.

Responsible for:
  * instantiating the devices from the config and calling setup();
  * building the Group Address -> data point routing table;
  * delivering incoming telegrams to the right device;
  * access to the devices by name (for the control interface);
  * starting/stopping the devices' background tasks.
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

    # --- building ------------------------------------------------------------
    def build(self, config: AppConfig) -> None:
        for entry in config.devices:
            device = self._registry.create(
                entry.type, entry.name, entry.config, self._bus
            )
            device.setup()
            self.devices_by_name[entry.name] = device
            self._register_routes(device)
            log.info("Created device '%s' (type=%s)", entry.name, entry.type)

    def _register_routes(self, device: BaseDevice) -> None:
        for dp in device.datapoints:
            if isinstance(dp, ActionPoint):
                if dp.ga in self._action_routes:
                    other = self._action_routes[dp.ga]
                    raise DuplicateAddressError(
                        f"Action address {dp.ga} is already taken ({other!r}), "
                        f"conflicts with {dp!r} of '{device.name}'"
                    )
                self._action_routes[dp.ga] = dp
            if isinstance(dp, StatusPoint):
                self._status_routes.setdefault(dp.ga, []).append(dp)

    # --- routing of incoming telegrams ---------------------------------------
    def on_telegram(self, ga: GroupAddress, kind: str, raw) -> None:
        if kind == "write":
            point = self._action_routes.get(ga)
            if point is not None:
                point.handle_write(raw)  # handle_write does the logging
            else:
                log.debug("WRITE %s — no device at this address, ignoring", ga)
        elif kind == "read":
            points = self._status_routes.get(ga, [])
            if not points:
                log.debug("READ %s — no device at this address, ignoring", ga)
            for point in points:
                value = point.read()
                point.device.log.info(
                    "KNX -> status request '%s' (%s): answering with %r",
                    point.name, ga, value,
                )
                self._bus.schedule_response(point.ga, point.dpt, value)
        # kind == "response" is ignored — we do not poll other devices' statuses

    def get_device(self, name: str) -> BaseDevice | None:
        return self.devices_by_name.get(name)

    # --- life cycle ----------------------------------------------------------
    async def start_all(self) -> None:
        for device in self.devices_by_name.values():
            device.publish_all_status()  # initial status broadcast at start-up
            await device.start()

    async def stop_all(self) -> None:
        for device in self.devices_by_name.values():
            await device.stop()
