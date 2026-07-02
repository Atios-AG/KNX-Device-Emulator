"""Tests for KNX DPT parsing and payload codec."""

from __future__ import annotations

import unittest

from knx_emulator.knx.codec import (
    decode_payload,
    default_value_for_dpt,
    encode_payload,
)
from knx_emulator.knx.dpt import normalize_dpt, numeric_dpt_to_str, parse_dpt_from_info


class CodecTests(unittest.TestCase):
    def test_dpt_normalization(self) -> None:
        self.assertEqual(numeric_dpt_to_str(1001), "1.001")
        self.assertEqual(numeric_dpt_to_str(5001), "5.001")
        self.assertEqual(normalize_dpt("20.102"), "20.102")
        self.assertEqual(normalize_dpt("1.1"), "1.001")
        self.assertEqual(
            parse_dpt_from_info("DPT 9.001 Temperature deg C"),
            "9.001",
        )

    def test_supported_dpt_roundtrip(self) -> None:
        samples = {
            "1.001": True,
            "1.100": False,
            "5.001": 50,
            "9.001": 21.5,
            "20.102": 3,
        }

        for dpt, value in samples.items():
            with self.subTest(dpt=dpt):
                payload = encode_payload(dpt, value)
                self.assertEqual(decode_payload(dpt, payload), value)

    def test_default_values(self) -> None:
        self.assertIs(default_value_for_dpt("1.001"), False)
        self.assertEqual(default_value_for_dpt("5.001"), 0)
        self.assertEqual(default_value_for_dpt("9.001"), 20.0)
        self.assertEqual(default_value_for_dpt("20.102"), 0)


if __name__ == "__main__":
    unittest.main()
