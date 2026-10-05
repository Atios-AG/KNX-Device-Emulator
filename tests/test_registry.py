from core.registry import DeviceRegistry


def test_discover_finds_plugins():
    registry = DeviceRegistry()
    registry.discover("devices")
    assert "outlet" in registry.types
    assert "dimmer" in registry.types
    assert "thermostat" in registry.types


def test_unknown_type_raises():
    import pytest

    from core.exceptions import UnknownDeviceTypeError

    registry = DeviceRegistry()
    registry.discover("devices")
    with pytest.raises(UnknownDeviceTypeError):
        registry.create("does_not_exist", "x", None, None)
