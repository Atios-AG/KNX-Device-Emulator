"""Virtual device type registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from .base import VirtualDevice

DeviceType = type[VirtualDevice]
TDevice = TypeVar("TDevice", bound=DeviceType)

_REGISTRY: dict[int, DeviceType] = {}


def register_device(*, type_ids: set[int]) -> Callable[[TDevice], TDevice]:
    """Register a virtual device class for Atios accessory type ids."""

    def decorator(device_cls: TDevice) -> TDevice:
        for type_id in type_ids:
            _REGISTRY[type_id] = device_cls
        device_cls.type_ids = set(type_ids)
        return device_cls

    return decorator


def get_device_class(type_id: int) -> DeviceType:
    """Return the registered device class or GenericDevice fallback."""
    from .generic import GenericDevice

    return _REGISTRY.get(type_id, GenericDevice)


def registered_type_ids() -> tuple[int, ...]:
    """Return known Atios accessory type ids."""
    return tuple(sorted(_REGISTRY))
