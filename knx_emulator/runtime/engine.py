"""Runtime engine for device routing and lifecycle."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from knx_emulator.config import (
    AccessoryConfig,
    CharacteristicConfig,
    EmulatorConfig,
)
import knx_emulator.devices  # noqa: F401
from knx_emulator.devices.base import VirtualDevice
from knx_emulator.devices.registry import get_device_class
from knx_emulator.knx.bus import BusTelegram, KnxBus
from knx_emulator.knx.codec import parse_value_for_dpt

from .state import StateStore

logger = logging.getLogger(__name__)

AddressRole = Literal["control", "status"]


@dataclass(frozen=True)
class AddressRoute:
    """Route from a KNX group address to a virtual device characteristic."""

    device: VirtualDevice
    accessory: AccessoryConfig
    characteristic: CharacteristicConfig
    role: AddressRole


class RuntimeEngine:
    """Create virtual devices and route KNX telegrams to them."""

    def __init__(
        self,
        config: EmulatorConfig,
        bus: KnxBus,
        state: StateStore | None = None,
    ) -> None:
        self.config = config
        self.bus = bus
        self.state = state or StateStore()
        self.devices: list[VirtualDevice] = []
        self._routes: dict[str, AddressRoute] = {}
        self._build_devices()

    async def start(self) -> None:
        """Start routing telegrams and device lifecycle hooks."""
        logger.info(
            "Starting runtime engine with %s devices and %s routed addresses",
            len(self.devices),
            len(self._routes),
        )
        self.bus.subscribe(self.handle_telegram)
        for device in self.devices:
            await device.start()

    async def stop(self) -> None:
        """Stop device lifecycle hooks and remove the bus subscription."""
        logger.info("Stopping runtime engine")
        self.bus.unsubscribe(self.handle_telegram)
        for device in reversed(self.devices):
            await device.stop()

    async def handle_telegram(self, telegram: BusTelegram) -> None:
        """Route an incoming normalized KNX telegram."""
        route = self._routes.get(telegram.address)
        if route is None:
            logger.info(
                "Ignoring %s telegram for unconfigured address=%s dpt=%s "
                "value=%r",
                telegram.kind,
                telegram.address,
                telegram.dpt,
                telegram.value,
            )
            return

        logger.info(
            "Routing %s address=%s dpt=%s value=%r -> device=%s "
            "type=%s characteristic=%s role=%s",
            telegram.kind,
            telegram.address,
            route.characteristic.dpt,
            telegram.value,
            route.accessory.name,
            route.accessory.type_id,
            route.characteristic.name,
            route.role,
        )

        if telegram.kind == "read":
            await route.device.on_group_read(
                route.characteristic,
                telegram.address,
            )
            return

        if telegram.kind != "write":
            logger.debug(
                "Ignoring %s telegram for address=%s after route lookup",
                telegram.kind,
                telegram.address,
            )
            return

        if route.role != "control":
            logger.debug(
                "Ignoring write to status address %s for %s / %s",
                telegram.address,
                route.accessory.name,
                route.characteristic.name,
            )
            return

        await route.device.on_group_write(route.characteristic, telegram.value)

    async def set_local_value(
        self,
        device_selector: str,
        characteristic_selector: str,
        value_text: str,
    ) -> None:
        """Set a local virtual device value and publish its KNX status."""
        route = self._find_device_characteristic(
            device_selector,
            characteristic_selector,
        )
        value = parse_value_for_dpt(route.characteristic.dpt, value_text)
        logger.info(
            "Local control set device=%s characteristic=%s dpt=%s value=%r",
            route.accessory.name,
            route.characteristic.name,
            route.characteristic.dpt,
            value,
        )
        await route.device.on_local_update(route.characteristic, value)

    def list_devices(self) -> tuple[str, ...]:
        """Return a human-readable list of configured virtual devices."""
        lines: list[str] = []
        for device in self.devices:
            lines.append(
                f"{device.config.name} (id={device.config.id}, "
                f"type={device.config.type_id}, class={type(device).__name__})"
            )
            for characteristic in device.config.characteristics:
                lines.append(
                    "  "
                    f"{characteristic.name}: dpt={characteristic.dpt}, "
                    f"control={characteristic.control_address}, "
                    f"status={characteristic.status_address}"
                )
        return tuple(lines)

    def list_state(self) -> tuple[str, ...]:
        """Return current state values for all known characteristics."""
        lines: list[str] = []
        for device in self.devices:
            lines.append(f"{device.config.name}:")
            for characteristic in device.config.characteristics:
                value = self.state.get(device.config.id, characteristic.name)
                lines.append(f"  {characteristic.name} = {value!r}")
        return tuple(lines)

    def _build_devices(self) -> None:
        for accessory in self.config.accessories:
            if not accessory.enabled:
                continue

            device_cls = get_device_class(accessory.type_id)
            device = device_cls(accessory, self.bus, self.state)
            self.devices.append(device)
            self._register_routes(accessory, device)

    def _register_routes(
        self,
        accessory: AccessoryConfig,
        device: VirtualDevice,
    ) -> None:
        for characteristic in accessory.characteristics:
            if characteristic.control_address is not None:
                self._register_route(
                    characteristic.control_address,
                    characteristic.dpt,
                    AddressRoute(device, accessory, characteristic, "control"),
                )
            if characteristic.status_address is not None:
                self._register_route(
                    characteristic.status_address,
                    characteristic.dpt,
                    AddressRoute(device, accessory, characteristic, "status"),
                )

    def _register_route(
        self,
        address: str,
        dpt: str,
        route: AddressRoute,
    ) -> None:
        self.bus.register_address(address, dpt)
        self._routes[address] = route
        logger.debug(
            "Registered route address=%s dpt=%s -> device=%s "
            "characteristic=%s role=%s",
            address,
            dpt,
            route.accessory.name,
            route.characteristic.name,
            route.role,
        )

    @property
    def route_count(self) -> int:
        """Return the number of routed group addresses."""
        return len(self._routes)

    def _find_device_characteristic(
        self,
        device_selector: str,
        characteristic_selector: str,
    ) -> AddressRoute:
        device_query = device_selector.casefold()
        characteristic_query = characteristic_selector.casefold()
        matches: list[AddressRoute] = []

        for route in self._routes.values():
            if route.accessory.name.casefold() != device_query and (
                route.accessory.id.casefold() != device_query
            ):
                continue
            if route.characteristic.name.casefold() != characteristic_query:
                continue
            if route.role == "status":
                continue
            matches.append(route)

        if not matches:
            for route in self._routes.values():
                if route.accessory.name.casefold() != device_query and (
                    route.accessory.id.casefold() != device_query
                ):
                    continue
                if route.characteristic.name.casefold() == characteristic_query:
                    matches.append(route)
                    break

        if not matches:
            raise ValueError(
                f"Unknown device/characteristic: "
                f"{device_selector!r} {characteristic_selector!r}"
            )

        return matches[0]
