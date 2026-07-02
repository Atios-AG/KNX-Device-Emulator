"""Encode and decode KNX DPT payloads."""

from __future__ import annotations

from typing import Any

from xknx.dpt import (
    DPT4ByteFloat,
    DPTArray,
    DPTBinary,
    DPTScaling,
    DPTTemperature,
)
from xknx.telegram.apci import GroupValueResponse, GroupValueWrite

from .dpt import dpt_main_number, normalize_dpt

KnxPayload = DPTBinary | DPTArray


def encode_payload(dpt: str, value: Any) -> KnxPayload:
    """Encode a Python value into a KNX DPT payload."""
    normalized = normalize_dpt(dpt)
    main_number = dpt_main_number(normalized)

    if main_number == 1:
        return DPTBinary(_to_bool_int(value))

    if normalized == "5.001":
        return DPTScaling.to_knx(_to_float(value))

    if normalized == "9.001":
        return DPTTemperature.to_knx(_to_float(value))

    if main_number == 14:
        return DPT4ByteFloat.to_knx(_to_float(value))

    if main_number == 20:
        return DPTArray((_to_byte(value),))

    raise UnsupportedDPTError(f"Encoding is not supported for DPT {normalized}")


def decode_payload(dpt: str, payload: Any) -> Any:
    """Decode a KNX DPT payload into a Python value."""
    payload = _extract_payload(payload)
    normalized = normalize_dpt(dpt)
    main_number = dpt_main_number(normalized)

    if main_number == 1:
        if not isinstance(payload, DPTBinary):
            raise TypeError(f"DPT {normalized} expects DPTBinary payload")
        return bool(payload.value)

    if normalized == "5.001":
        return DPTScaling.from_knx(_require_array(normalized, payload))

    if normalized == "9.001":
        return DPTTemperature.from_knx(_require_array(normalized, payload))

    if main_number == 14:
        return DPT4ByteFloat.from_knx(_require_array(normalized, payload))

    if main_number == 20:
        array = _require_array(normalized, payload)
        return int(array.value[0])

    raise UnsupportedDPTError(f"Decoding is not supported for DPT {normalized}")


def encode_group_value_write(dpt: str, value: Any) -> GroupValueWrite:
    """Encode a Python value as a GroupValueWrite APCI payload."""
    return GroupValueWrite(encode_payload(dpt, value))


def encode_group_value_response(dpt: str, value: Any) -> GroupValueResponse:
    """Encode a Python value as a GroupValueResponse APCI payload."""
    return GroupValueResponse(encode_payload(dpt, value))


def default_value_for_dpt(dpt: str) -> Any:
    """Return a conservative initial device state value for a supported DPT."""
    normalized = normalize_dpt(dpt)
    main_number = dpt_main_number(normalized)

    if main_number == 1:
        return False

    if normalized == "5.001":
        return 0

    if normalized == "9.001":
        return 20.0

    if main_number == 14:
        return 0.0

    if main_number == 20:
        return 0

    raise UnsupportedDPTError(f"Default value is not supported for DPT {normalized}")


def parse_value_for_dpt(dpt: str, value: str) -> Any:
    """Parse a local console value according to the given DPT."""
    normalized = normalize_dpt(dpt)
    main_number = dpt_main_number(normalized)
    text = value.strip()

    if main_number == 1:
        lowered = text.lower()
        if lowered in {"1", "true", "on", "yes"}:
            return True
        if lowered in {"0", "false", "off", "no"}:
            return False
        raise ValueError(f"Expected boolean value for DPT {normalized}: {value!r}")

    if normalized == "5.001":
        number = int(text)
        if not 0 <= number <= 100:
            raise ValueError(f"Expected percentage 0..100 for DPT {normalized}")
        return number

    if normalized == "9.001":
        return float(text)

    if main_number == 14:
        return float(text)

    if main_number == 20:
        number = int(text)
        if not 0 <= number <= 255:
            raise ValueError(f"Expected enum value 0..255 for DPT {normalized}")
        return number

    raise UnsupportedDPTError(f"Parsing is not supported for DPT {normalized}")


class UnsupportedDPTError(ValueError):
    """Raised when the codec does not support a DPT."""


def _extract_payload(payload: Any) -> Any:
    if isinstance(payload, GroupValueWrite | GroupValueResponse):
        return payload.value
    return payload


def _require_array(dpt: str, payload: Any) -> DPTArray:
    if not isinstance(payload, DPTArray):
        raise TypeError(f"DPT {dpt} expects DPTArray payload")
    return payload


def _to_bool_int(value: Any) -> int:
    if isinstance(value, str):
        return 1 if value.strip().lower() in {"1", "true", "on", "yes"} else 0
    return 1 if bool(value) else 0


def _to_float(value: Any) -> float:
    return float(value)


def _to_byte(value: Any) -> int:
    number = int(value)
    if not 0 <= number <= 255:
        raise ValueError(f"Value is outside 1-byte range: {value!r}")
    return number
