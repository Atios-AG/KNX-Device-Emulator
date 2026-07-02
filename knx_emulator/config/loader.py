"""Public configuration loading entry points."""

from __future__ import annotations

from pathlib import Path

from .models import EmulatorConfig
from .sources import select_loader
from .validators import validate_config


def load_config(
    path: str | Path,
    *,
    format_name: str | None = None,
    validate: bool = True,
) -> EmulatorConfig:
    """Load a config file and return the normalized emulator model."""
    config_path = Path(path)
    loader = select_loader(config_path, format_name)
    config = loader.load(config_path)

    if validate:
        validate_config(config)

    return config
