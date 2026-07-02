"""Virtual switch device implementation."""

from __future__ import annotations

from .generic import GenericDevice
from .registry import register_device


@register_device(type_ids={1})
class SwitchDevice(GenericDevice):
    """Virtual KNX switch."""
