"""Модель KNX Group Address.

Поддерживает 3-уровневый формат "main/middle/sub" (наиболее
распространённый) и сырое 16-битное представление. Используется как ключ
в таблицах маршрутизации, поэтому реализует __hash__/__eq__.
"""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import InvalidValueError

# Границы 3-уровневого адреса: main 0..31 (5 бит), middle 0..7 (3 бита),
# sub 0..255 (8 бит).
_MAIN_MAX = 31
_MIDDLE_MAX = 7
_SUB_MAX = 255


@dataclass(frozen=True)
class GroupAddress:
    raw: int  # 16-битное значение

    def __post_init__(self) -> None:
        if not (0 <= self.raw <= 0xFFFF):
            raise InvalidValueError(f"Group address вне диапазона: {self.raw}")

    # --- конструкторы --------------------------------------------------------
    @classmethod
    def from_string(cls, value: str) -> "GroupAddress":
        text = value.strip()
        parts = text.split("/")
        try:
            if len(parts) == 3:
                main, middle, sub = (int(p) for p in parts)
                if not (0 <= main <= _MAIN_MAX):
                    raise InvalidValueError(f"main вне 0..{_MAIN_MAX}: {value}")
                if not (0 <= middle <= _MIDDLE_MAX):
                    raise InvalidValueError(f"middle вне 0..{_MIDDLE_MAX}: {value}")
                if not (0 <= sub <= _SUB_MAX):
                    raise InvalidValueError(f"sub вне 0..{_SUB_MAX}: {value}")
                raw = (main << 11) | (middle << 8) | sub
                return cls(raw)
            if len(parts) == 1:
                return cls(int(text))
        except ValueError as exc:
            raise InvalidValueError(f"Не удалось разобрать адрес '{value}'") from exc
        raise InvalidValueError(
            f"Ожидался формат 'main/middle/sub' или число, получено '{value}'"
        )

    # --- представление -------------------------------------------------------
    @property
    def levels(self) -> tuple[int, int, int]:
        main = (self.raw >> 11) & 0x1F
        middle = (self.raw >> 8) & 0x07
        sub = self.raw & 0xFF
        return main, middle, sub

    def __str__(self) -> str:
        main, middle, sub = self.levels
        return f"{main}/{middle}/{sub}"

    def __repr__(self) -> str:
        return f"GroupAddress({self})"
