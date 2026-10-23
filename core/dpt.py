"""Data Point Type (DPT) codecs.

The lowest layer: the conversion "Python value <-> raw KNX payload". It does
not depend on anything in the project except the exceptions — easy to test in
isolation.

payload_kind:
  * "binary" — the value fits into 6 bits and is sent as DPTBinary(int);
               encode() returns an int, decode() accepts an int.
  * "array"  — one or several bytes, sent as DPTArray(bytes);
               encode() returns bytes, decode() accepts bytes.
"""

from __future__ import annotations

from .exceptions import DPTError


class DPT:
    main: int
    sub: int
    unit: str = ""
    payload_kind: str = "array"

    @property
    def dpt_id(self) -> str:
        return f"{self.main}.{self.sub:03d}"

    def encode(self, value):  # -> int | bytes
        raise NotImplementedError

    def decode(self, raw):  # raw: int | bytes
        raise NotImplementedError


class DPTBool(DPT):
    """1.001 — on/off switching (1 bit)."""

    main, sub = 1, 1
    payload_kind = "binary"

    def encode(self, value) -> int:
        return 1 if value else 0

    def decode(self, raw) -> bool:
        return bool(raw)


class DPTScaling(DPT):
    """5.001 — a 0..100 % scale in a single byte 0..255."""

    main, sub = 5, 1
    unit = "%"
    payload_kind = "array"

    def encode(self, value) -> bytes:
        try:
            v = float(value)
        except (TypeError, ValueError) as exc:
            raise DPTError(f"5.001 expects a number, got {value!r}") from exc
        if not (0.0 <= v <= 100.0):
            raise DPTError(f"5.001 out of range 0..100: {v}")
        return bytes([round(v * 255 / 100)])

    def decode(self, raw: bytes) -> float:
        if not raw:
            raise DPTError("5.001: empty payload")
        return round(raw[0] * 100 / 255, 1)


class DPT2ByteFloat(DPT):
    """Base codec of the KNX 2-byte float (class 9.xxx).

    The format is the same for all 9.xxx — the subclasses only set main/sub,
    unit and the range.
    """

    main, sub = 9, 0
    unit = ""
    payload_kind = "array"

    _MIN = -671088.64
    _MAX = 670760.96

    def encode(self, value) -> bytes:
        try:
            v = float(value)
        except (TypeError, ValueError) as exc:
            raise DPTError(f"{self.dpt_id} expects a number, got {value!r}") from exc
        if not (self._MIN <= v <= self._MAX):
            raise DPTError(f"{self.dpt_id} out of range {self._MIN}..{self._MAX}: {v}")
        scaled = v * 100.0
        exponent = 0
        while scaled < -2048.0 or scaled > 2047.0:
            scaled /= 2.0
            exponent += 1
        mantissa = int(round(scaled))
        sign = 0x8000 if mantissa < 0 else 0
        raw = sign | ((exponent & 0x0F) << 11) | (mantissa & 0x07FF)
        return bytes([(raw >> 8) & 0xFF, raw & 0xFF])

    def decode(self, raw: bytes) -> float:
        if len(raw) < 2:
            raise DPTError(f"{self.dpt_id}: 2 bytes expected")
        word = (raw[0] << 8) | raw[1]
        sign = (word >> 15) & 0x1
        exponent = (word >> 11) & 0x0F
        mantissa = word & 0x07FF
        if sign:
            mantissa -= 2048
        return round((mantissa << exponent) * 0.01, 2)


class DPTTemperature(DPT2ByteFloat):
    """9.001 — temperature, KNX 2-byte float."""

    main, sub = 9, 1
    unit = "°C"
    _MIN = -273.0
    _MAX = 670760.0


class DPTAirQualityPpm(DPT2ByteFloat):
    """9.008 — concentration in ppm (e.g. TVOC, CO2)."""

    main, sub = 9, 8
    unit = "ppm"
    _MIN = 0.0


class DPTConcentrationUgm3(DPT2ByteFloat):
    """9.030 — concentration in µg/m³ (e.g. CH2O, PM1.0/PM2.5/PM10)."""

    main, sub = 9, 30
    unit = "µg/m³"
    _MIN = 0.0


class DPTUCount(DPT):
    """5.010 — an unsigned 0..255 counter in a single byte (e.g. AQI)."""

    main, sub = 5, 10
    unit = ""
    payload_kind = "array"

    def encode(self, value) -> bytes:
        try:
            v = int(round(float(value)))
        except (TypeError, ValueError) as exc:
            raise DPTError(f"5.010 expects a number, got {value!r}") from exc
        if not (0 <= v <= 255):
            raise DPTError(f"5.010 out of range 0..255: {v}")
        return bytes([v])

    def decode(self, raw) -> int:
        if isinstance(raw, (bytes, bytearray)):
            if not raw:
                raise DPTError("5.010: empty payload")
            return raw[0]
        return int(raw)


class DPTColorTemperature(DPT):
    """7.600 — absolute color temperature in Kelvin, 2 bytes unsigned, big-endian."""

    main, sub = 7, 600
    unit = "K"
    payload_kind = "array"

    def encode(self, value) -> bytes:
        try:
            v = int(round(float(value)))
        except (TypeError, ValueError) as exc:
            raise DPTError(f"7.600 expects a number, got {value!r}") from exc
        if not (0 <= v <= 0xFFFF):
            raise DPTError(f"7.600 out of range 0..65535: {v}")
        return v.to_bytes(2, "big")

    def decode(self, raw: bytes) -> int:
        if len(raw) != 2:
            raise DPTError("7.600: 2 bytes expected")
        return int.from_bytes(raw, "big")


class DPTColor3Byte(DPT):
    """232.600 — three bytes 0..255: red, green, blue, or (MDT and the Atios
    KNX Bridge) hue, saturation, value. The value is the tuple of the bytes;
    what they mean is up to the device."""

    main, sub = 232, 600
    payload_kind = "array"

    def encode(self, value) -> bytes:
        try:
            out = bytes(int(b) for b in value)
        except (TypeError, ValueError) as exc:
            raise DPTError(f"232.600 expects three bytes 0..255, got {value!r}") from exc
        if len(out) != 3:
            raise DPTError(f"232.600 expects three bytes, got {value!r}")
        return out

    def decode(self, raw: bytes) -> tuple[int, int, int]:
        if len(raw) != 3:
            raise DPTError("232.600: 3 bytes expected")
        return tuple(raw)


# --- registry and factory ----------------------------------------------------
DPT_BOOL = DPTBool()
DPT_SCALING = DPTScaling()
DPT_TEMPERATURE = DPTTemperature()
DPT_UCOUNT = DPTUCount()
DPT_AIR_QUALITY_PPM = DPTAirQualityPpm()
DPT_CONCENTRATION_UGM3 = DPTConcentrationUgm3()
DPT_COLOR_TEMPERATURE = DPTColorTemperature()
DPT_COLOR_3BYTE = DPTColor3Byte()

_REGISTRY: dict[str, DPT] = {
    DPT_COLOR_TEMPERATURE.dpt_id: DPT_COLOR_TEMPERATURE,
    DPT_COLOR_3BYTE.dpt_id: DPT_COLOR_3BYTE,
    DPT_BOOL.dpt_id: DPT_BOOL,
    DPT_SCALING.dpt_id: DPT_SCALING,
    DPT_TEMPERATURE.dpt_id: DPT_TEMPERATURE,
    DPT_UCOUNT.dpt_id: DPT_UCOUNT,
    DPT_AIR_QUALITY_PPM.dpt_id: DPT_AIR_QUALITY_PPM,
    DPT_CONCENTRATION_UGM3.dpt_id: DPT_CONCENTRATION_UGM3,
}


def dpt_from_string(dpt_id: str) -> DPT:
    """Return the codec for an id like '1.001'."""
    key = dpt_id.strip()
    if key not in _REGISTRY:
        raise DPTError(f"Unknown DPT: {dpt_id}")
    return _REGISTRY[key]
