"""Typed hierarchy of simulator errors.

All the layers raise exceptions from here so that main.py and the transports
can tell the causes apart (broken config / no such device / bus error, etc.).
"""


class KnxSimError(Exception):
    """Base class for the project's exceptions."""


# --- configuration ----------------------------------------------------------
class ConfigError(KnxSimError):
    pass


class MissingSectionError(ConfigError):
    pass


class MissingOptionError(ConfigError):
    pass


class InvalidValueError(ConfigError):
    pass


# --- devices / plugins -------------------------------------------------------
class DeviceError(KnxSimError):
    pass


class UnknownDeviceTypeError(DeviceError):
    """The config specifies a type= for which there is no plugin."""


class UnknownDeviceError(DeviceError):
    """A device was looked up by a name that does not exist."""


class DuplicateAddressError(DeviceError):
    """Two devices listen on the same Action Group Address."""


class DuplicateTypeError(DeviceError):
    """Two plugins declared the same TYPE."""


# --- control commands --------------------------------------------------------
class CommandError(KnxSimError):
    pass


class UnknownCommandError(CommandError):
    pass


class CommandArgumentError(CommandError):
    pass


# --- value encoding ----------------------------------------------------------
class DPTError(KnxSimError):
    pass


# --- bus ---------------------------------------------------------------------
class BusError(KnxSimError):
    pass
