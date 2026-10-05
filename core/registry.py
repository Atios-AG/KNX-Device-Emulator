"""Auto-discovery of device plugins.

Implements the key goal of the project: "add a device with a single file".
Scans the devices/ package, imports every module (the import registers the
BaseDevice subclasses) and builds the {TYPE: class} registry.
"""

from __future__ import annotations

import importlib
import pkgutil

from .device import BaseDevice
from .exceptions import DuplicateTypeError, UnknownDeviceTypeError


class DeviceRegistry:
    def __init__(self):
        self._registry: dict[str, type[BaseDevice]] = {}

    def discover(self, package: str = "devices") -> dict[str, type[BaseDevice]]:
        pkg = importlib.import_module(package)
        for module_info in pkgutil.iter_modules(pkg.__path__):
            if module_info.name.startswith("_"):
                continue
            importlib.import_module(f"{package}.{module_info.name}")
        self._collect()
        return self._registry

    def _collect(self) -> None:
        def walk(cls):
            for sub in cls.__subclasses__():
                if getattr(sub, "TYPE", ""):
                    if sub.TYPE in self._registry and self._registry[sub.TYPE] is not sub:
                        raise DuplicateTypeError(
                            f"Two plugins with TYPE='{sub.TYPE}': "
                            f"{self._registry[sub.TYPE].__name__} and {sub.__name__}"
                        )
                    self._registry[sub.TYPE] = sub
                walk(sub)

        walk(BaseDevice)

    def create(self, type_name: str, name: str, config, bus) -> BaseDevice:
        cls = self._registry.get(type_name)
        if cls is None:
            raise UnknownDeviceTypeError(
                f"Unknown device type '{type_name}'. "
                f"Available: {sorted(self._registry)}"
            )
        return cls(name=name, config=config, bus=bus)

    @property
    def types(self) -> list[str]:
        return sorted(self._registry)
