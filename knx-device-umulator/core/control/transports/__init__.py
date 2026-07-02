"""Выбор транспорта управления по имени."""

from __future__ import annotations

from .base import ControlTransport
from .cli import CliTransport
from .rest import RestTransport

_TRANSPORTS = {
    RestTransport.NAME: RestTransport,
    CliTransport.NAME: CliTransport,
}


def create_transport(name: str, interface, config) -> ControlTransport:
    cls = _TRANSPORTS.get((name or "rest").lower())
    if cls is None:
        raise ValueError(
            f"Неизвестный транспорт управления '{name}'. "
            f"Доступны: {sorted(_TRANSPORTS)}"
        )
    return cls(interface, config)
