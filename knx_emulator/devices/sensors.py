"""Virtual sensor device implementations."""

from __future__ import annotations

from .generic import GenericDevice
from .registry import register_device


@register_device(type_ids={9, 15, 34, 40, 41})
class SensorDevice(GenericDevice):
    """Virtual read-oriented KNX sensor."""
