"""Tests for configuration loading and validation."""

from __future__ import annotations

import unittest

from knx_emulator.config import (
    AccessoryConfig,
    CharacteristicConfig,
    ConfigValidationError,
    EmulatorConfig,
    load_config,
    validate_config,
)


class ConfigTests(unittest.TestCase):
    def test_load_current_atios_config(self) -> None:
        config = load_config("Atios.json")

        self.assertEqual(config.source_format, "atios-json")
        self.assertEqual(len(config.accessories), 2)
        self.assertEqual(
            sum(len(accessory.characteristics) for accessory in config.accessories),
            13,
        )
        self.assertEqual(
            sorted({characteristic.dpt for accessory in config.accessories for characteristic in accessory.characteristics}),
            ["1.001", "1.100", "20.102", "5.001", "9.001"],
        )

    def test_duplicate_group_address_is_invalid(self) -> None:
        characteristic_a = CharacteristicConfig(
            name="A",
            dpt="1.001",
            status_address="1/1/1",
        )
        characteristic_b = CharacteristicConfig(
            name="B",
            dpt="1.001",
            control_address="1/1/1",
        )
        config = EmulatorConfig(
            accessories=(
                AccessoryConfig(
                    id="a",
                    name="Device A",
                    type_id=1,
                    characteristics=(characteristic_a,),
                ),
                AccessoryConfig(
                    id="b",
                    name="Device B",
                    type_id=2,
                    characteristics=(characteristic_b,),
                ),
            ),
            source_format="test",
        )

        with self.assertRaises(ConfigValidationError):
            validate_config(config)


if __name__ == "__main__":
    unittest.main()
