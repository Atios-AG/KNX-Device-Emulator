"""Command-line interface for the KNX emulator."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .config import ConfigValidationError, load_config
from .app import run_emulator


def main() -> None:
    """Run the command-line interface."""
    parser = _build_parser()
    args = parser.parse_args()

    try:
        args.func(args)
    except ConfigValidationError as error:
        print(error)
        raise SystemExit(1) from error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Virtual KNX device emulator."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an emulator configuration file.",
    )
    validate_parser.add_argument("config", type=Path)
    validate_parser.add_argument("--format", dest="format_name")
    validate_parser.set_defaults(func=_validate_command)

    dump_parser = subparsers.add_parser(
        "dump-config",
        help="Print the normalized emulator configuration as JSON.",
    )
    dump_parser.add_argument("config", type=Path)
    dump_parser.add_argument("--format", dest="format_name")
    dump_parser.set_defaults(func=_dump_config_command)

    simulate_parser = subparsers.add_parser(
        "simulate",
        help="Run virtual KNX devices against a KNX/IP gateway.",
    )
    simulate_parser.add_argument("config", type=Path)
    simulate_parser.add_argument("--format", dest="format_name")
    simulate_parser.add_argument("--gateway", "-g", required=True)
    simulate_parser.add_argument("--port", "-p", type=int, default=3671)
    simulate_parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging verbosity for emulator activity.",
    )
    simulate_parser.set_defaults(func=_simulate_command)

    return parser


def _validate_command(args: argparse.Namespace) -> None:
    config = load_config(args.config, format_name=args.format_name)
    print(
        "OK: "
        f"{len(config.accessories)} accessories, "
        f"{sum(len(accessory.characteristics) for accessory in config.accessories)} "
        "characteristics"
    )


def _dump_config_command(args: argparse.Namespace) -> None:
    config = load_config(args.config, format_name=args.format_name)
    print(json.dumps(_to_jsonable(config), ensure_ascii=False, indent=2))


def _simulate_command(args: argparse.Namespace) -> None:
    try:
        asyncio.run(
            run_emulator(
                args.config,
                gateway_ip=args.gateway,
                gateway_port=args.port,
                format_name=args.format_name,
                log_level=args.log_level,
            )
        )
    except KeyboardInterrupt:
        print("Emulator stopped.")


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list | set | frozenset):
        return [_to_jsonable(item) for item in value]
    return value
