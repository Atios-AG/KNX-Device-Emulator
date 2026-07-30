"""Кодеки Data Point Types (DPT).

Самый нижний слой: перевод "питоновское значение <-> сырой полезный груз KNX".
Не зависит ни от чего из проекта, кроме исключений, — легко тестируется в изоляции.

payload_kind:
  * "binary" — значение помещается в 6 бит, на шину уходит как DPTBinary(int);
               encode() возвращает int, decode() принимает int.
  * "array"  — один или несколько байт, на шину уходит как DPTArray(bytes);
               encode() возвращает bytes, decode() принимает bytes.
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
    """1.001 — переключение вкл/выкл (1 бит)."""

    main, sub = 1, 1
    payload_kind = "binary"

    def encode(self, value) -> int:
        return 1 if value else 0

    def decode(self, raw) -> bool:
        return bool(raw)


class DPTScaling(DPT):
    """5.001 — масштаб 0..100 % в одном байте 0..255."""

    main, sub = 5, 1
    unit = "%"
    payload_kind = "array"

    def encode(self, value) -> bytes:
        try:
            v = float(value)
        except (TypeError, ValueError) as exc:
            raise DPTError(f"5.001 ожидает число, получено {value!r}") from exc
        if not (0.0 <= v <= 100.0):
            raise DPTError(f"5.001 вне диапазона 0..100: {v}")
        return bytes([round(v * 255 / 100)])

    def decode(self, raw: bytes) -> float:
        if not raw:
            raise DPTError("5.001: пустой полезный груз")
        return round(raw[0] * 100 / 255, 1)


class DPT2ByteFloat(DPT):
    """Базовый кодек 2-байтного float KNX (класс 9.xxx).

    Формат один на все 9.xxx — подклассы задают лишь main/sub, unit и диапазон.
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
            raise DPTError(f"{self.dpt_id} ожидает число, получено {value!r}") from exc
        if not (self._MIN <= v <= self._MAX):
            raise DPTError(f"{self.dpt_id} вне диапазона {self._MIN}..{self._MAX}: {v}")
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
            raise DPTError(f"{self.dpt_id}: ожидалось 2 байта")
        word = (raw[0] << 8) | raw[1]
        sign = (word >> 15) & 0x1
        exponent = (word >> 11) & 0x0F
        mantissa = word & 0x07FF
        if sign:
            mantissa -= 2048
        return round((mantissa << exponent) * 0.01, 2)


class DPTTemperature(DPT2ByteFloat):
    """9.001 — температура, 2-байтный float KNX."""

    main, sub = 9, 1
    unit = "°C"
    _MIN = -273.0
    _MAX = 670760.0


class DPTAirQualityPpm(DPT2ByteFloat):
    """9.008 — концентрация в ppm (напр. TVOC, CO2)."""

    main, sub = 9, 8
    unit = "ppm"
    _MIN = 0.0


class DPTConcentrationUgm3(DPT2ByteFloat):
    """9.030 — концентрация в µg/m³ (напр. CH2O, PM1.0/PM2.5/PM10)."""

    main, sub = 9, 30
    unit = "µg/m³"
    _MIN = 0.0


class DPTUCount(DPT):
    """5.010 — счётчик 0..255 в одном байте без знака (напр. AQI)."""

    main, sub = 5, 10
    unit = ""
    payload_kind = "array"

    def encode(self, value) -> bytes:
        try:
            v = int(round(float(value)))
        except (TypeError, ValueError) as exc:
            raise DPTError(f"5.010 ожидает число, получено {value!r}") from exc
        if not (0 <= v <= 255):
            raise DPTError(f"5.010 вне диапазона 0..255: {v}")
        return bytes([v])

    def decode(self, raw) -> int:
        if isinstance(raw, (bytes, bytearray)):
            if not raw:
                raise DPTError("5.010: пустой полезный груз")
            return raw[0]
        return int(raw)


# --- реестр и фабрика --------------------------------------------------------
DPT_BOOL = DPTBool()
DPT_SCALING = DPTScaling()
DPT_TEMPERATURE = DPTTemperature()
DPT_UCOUNT = DPTUCount()
DPT_AIR_QUALITY_PPM = DPTAirQualityPpm()
DPT_CONCENTRATION_UGM3 = DPTConcentrationUgm3()

_REGISTRY: dict[str, DPT] = {
    DPT_BOOL.dpt_id: DPT_BOOL,
    DPT_SCALING.dpt_id: DPT_SCALING,
    DPT_TEMPERATURE.dpt_id: DPT_TEMPERATURE,
    DPT_UCOUNT.dpt_id: DPT_UCOUNT,
    DPT_AIR_QUALITY_PPM.dpt_id: DPT_AIR_QUALITY_PPM,
    DPT_CONCENTRATION_UGM3.dpt_id: DPT_CONCENTRATION_UGM3,
}


def dpt_from_string(dpt_id: str) -> DPT:
    """Вернуть кодек по идентификатору вида '1.001'."""
    key = dpt_id.strip()
    if key not in _REGISTRY:
        raise DPTError(f"Неизвестный DPT: {dpt_id}")
    return _REGISTRY[key]
