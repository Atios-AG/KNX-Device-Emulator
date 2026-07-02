"""Типизированная иерархия ошибок симулятора.

Все слои бросают исключения отсюда, чтобы main.py и транспорты могли
различать причины (битый конфиг / нет такого устройства / ошибка шины и т.д.).
"""


class KnxSimError(Exception):
    """Базовое исключение проекта."""


# --- конфигурация -----------------------------------------------------------
class ConfigError(KnxSimError):
    pass


class MissingSectionError(ConfigError):
    pass


class MissingOptionError(ConfigError):
    pass


class InvalidValueError(ConfigError):
    pass


# --- устройства / плагины ----------------------------------------------------
class DeviceError(KnxSimError):
    pass


class UnknownDeviceTypeError(DeviceError):
    """В конфиге указан type=, для которого нет плагина."""


class UnknownDeviceError(DeviceError):
    """Обращение по имени к несуществующему инстансу устройства."""


class DuplicateAddressError(DeviceError):
    """Два устройства слушают один и тот же Action Group Address."""


class DuplicateTypeError(DeviceError):
    """Два плагина объявили одинаковый TYPE."""


# --- команды управления ------------------------------------------------------
class CommandError(KnxSimError):
    pass


class UnknownCommandError(CommandError):
    pass


class CommandArgumentError(CommandError):
    pass


# --- кодирование значений ----------------------------------------------------
class DPTError(KnxSimError):
    pass


# --- шина --------------------------------------------------------------------
class BusError(KnxSimError):
    pass
