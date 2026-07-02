"""Virtual outlet device implementation."""

from __future__ import annotations

from .generic import GenericDevice
from .registry import register_device


@register_device(type_ids={2})
class OutletDevice(GenericDevice):
    """Virtual KNX outlet."""
