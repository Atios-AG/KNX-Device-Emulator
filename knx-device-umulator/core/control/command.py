"""Транспортно-независимая модель команды управления."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Command:
    device: str
    name: str
    args: dict = field(default_factory=dict)

    @classmethod
    def from_line(cls, line: str) -> "Command":
        """Разбор строки CLI: 'outlet0 set on=true' / 'dimmer toggle'."""
        tokens = line.split()
        if len(tokens) < 2:
            raise ValueError("Формат: <device> <command> [key=value ...]")
        device, name, *rest = tokens
        args: dict = {}
        for token in rest:
            if "=" not in token:
                raise ValueError(f"Аргумент должен быть key=value: '{token}'")
            key, value = token.split("=", 1)
            args[key] = value
        return cls(device=device, name=name, args=args)


@dataclass
class CommandResult:
    ok: bool
    device: str
    state: dict | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        out: dict = {"ok": self.ok, "device": self.device}
        if self.state is not None:
            out["state"] = self.state
        if self.error is not None:
            out["error"] = self.error
        return out
