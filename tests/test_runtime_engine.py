"""Tests for runtime routing behavior."""

from __future__ import annotations

import unittest

from knx_emulator.config import load_config
import knx_emulator.devices  # noqa: F401
from knx_emulator.devices.registry import get_device_class, registered_type_ids
from knx_emulator.knx.bus import BusTelegram
from knx_emulator.runtime.engine import RuntimeEngine
from knx_emulator.app import handle_local_command


class FakeBus:
    def __init__(self) -> None:
        self.address_dpts: dict[str, str] = {}
        self.callbacks = []
        self.writes = []
        self.responses = []

    def register_address(self, address: str, dpt: str) -> None:
        self.address_dpts[address] = dpt

    def subscribe(self, callback) -> None:
        self.callbacks.append(callback)

    def unsubscribe(self, callback) -> None:
        self.callbacks.remove(callback)

    async def write(self, address: str, dpt: str, value) -> None:
        self.writes.append((address, dpt, value))

    async def response(self, address: str, dpt: str, value) -> None:
        self.responses.append((address, dpt, value))


class RuntimeEngineTests(unittest.IsolatedAsyncioTestCase):
    def test_core_device_types_are_registered(self) -> None:
        self.assertEqual(get_device_class(1).__name__, "SwitchDevice")
        self.assertEqual(get_device_class(2).__name__, "OutletDevice")
        self.assertEqual(get_device_class(15).__name__, "SensorDevice")
        self.assertEqual(get_device_class(30).__name__, "ClimateDevice")
        self.assertEqual(get_device_class(47).__name__, "ClimateDevice")
        self.assertIn(41, registered_type_ids())

    async def test_climate_devices_route_writes_and_reads(self) -> None:
        config = load_config("Atios.json")
        bus = FakeBus()
        engine = RuntimeEngine(config, bus)

        await engine.start()
        try:
            self.assertEqual([type(device).__name__ for device in engine.devices], ["ClimateDevice", "ClimateDevice"])
            self.assertEqual(engine.route_count, 17)
            self.assertEqual(len(bus.address_dpts), 17)

            await engine.handle_telegram(
                BusTelegram(kind="write", address="1/1/4", dpt="20.102", value=3)
            )
            self.assertEqual(bus.writes[-1], ("1/1/5", "20.102", 3))

            await engine.handle_telegram(
                BusTelegram(kind="read", address="1/1/5", dpt="20.102")
            )
            self.assertEqual(bus.responses[-1], ("1/1/5", "20.102", 3))
        finally:
            await engine.stop()

        self.assertEqual(bus.callbacks, [])

    async def test_device_commands_are_logged(self) -> None:
        config = load_config("Atios.json")
        bus = FakeBus()
        engine = RuntimeEngine(config, bus)

        await engine.start()
        try:
            with self.assertLogs("knx_emulator", level="INFO") as logs:
                await engine.handle_telegram(
                    BusTelegram(
                        kind="write",
                        address="1/1/4",
                        dpt="20.102",
                        value=3,
                    )
                )
        finally:
            await engine.stop()

        output = "\n".join(logs.output)
        self.assertIn("Routing write address=1/1/4", output)
        self.assertIn("Thermostat interpreted WRITE", output)
        self.assertIn("Thermostat publish STATUS address=1/1/5", output)

    async def test_local_set_publishes_status(self) -> None:
        config = load_config("Atios.json")
        bus = FakeBus()
        engine = RuntimeEngine(config, bus)

        await engine.start()
        try:
            await engine.set_local_value(
                "Thermostat",
                "TargetTemperature",
                "23.5",
            )
            self.assertEqual(bus.writes[-1], ("1/1/2", "9.001", 23.5))

            await engine.handle_telegram(
                BusTelegram(kind="read", address="1/1/2", dpt="9.001")
            )
            self.assertEqual(bus.responses[-1], ("1/1/2", "9.001", 23.5))
        finally:
            await engine.stop()

    async def test_local_command_supports_quoted_device_names(self) -> None:
        config = load_config("Atios.json")
        bus = FakeBus()
        engine = RuntimeEngine(config, bus)

        await engine.start()
        try:
            should_continue = await handle_local_command(
                engine,
                'set "Room AC" RotationSpeed 75',
                echo=False,
            )
            self.assertTrue(should_continue)
            self.assertEqual(bus.writes[-1], ("2/1/10", "5.001", 75))
        finally:
            await engine.stop()


if __name__ == "__main__":
    unittest.main()
