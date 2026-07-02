"""In-memory runtime state store."""

from __future__ import annotations

from typing import Any


class StateStore:
    """Simple in-memory state storage keyed by accessory id and characteristic."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], Any] = {}

    def get(self, accessory_id: str, characteristic_name: str) -> Any:
        """Return the stored value for a characteristic."""
        return self._values.get((accessory_id, characteristic_name))

    def set(
        self,
        accessory_id: str,
        characteristic_name: str,
        value: Any,
    ) -> None:
        """Store a characteristic value."""
        self._values[(accessory_id, characteristic_name)] = value

    def has(self, accessory_id: str, characteristic_name: str) -> bool:
        """Return True when the state store has a value for a characteristic."""
        return (accessory_id, characteristic_name) in self._values
