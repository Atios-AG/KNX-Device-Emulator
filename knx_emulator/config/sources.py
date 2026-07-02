"""Configuration source discovery and selection."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import EmulatorConfig


class ConfigLoader(Protocol):
    """Common contract for file-backed configuration loaders."""

    format_name: str

    def can_load(self, path: Path) -> bool:
        """Return True when this loader supports the given path."""

    def load(self, path: Path) -> EmulatorConfig:
        """Load and normalize a configuration file."""


def available_loaders() -> tuple[ConfigLoader, ...]:
    """Return registered configuration loaders."""
    from .atios_json import AtiosJsonLoader

    return (AtiosJsonLoader(),)


def select_loader(path: Path, format_name: str | None = None) -> ConfigLoader:
    """Select a configuration loader by explicit format or file path."""
    loaders = available_loaders()

    if format_name is not None:
        for loader in loaders:
            if loader.format_name == format_name:
                return loader
        raise ValueError(f"Unsupported config format: {format_name}")

    for loader in loaders:
        if loader.can_load(path):
            return loader

    raise ValueError(f"Unsupported config file type: {path}")
