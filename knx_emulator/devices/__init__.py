"""Virtual device implementations."""

from .climate import ClimateDevice
from .generic import GenericDevice
from .outlet import OutletDevice
from .sensors import SensorDevice
from .switch import SwitchDevice

__all__ = [
    "ClimateDevice",
    "GenericDevice",
    "OutletDevice",
    "SensorDevice",
    "SwitchDevice",
]
