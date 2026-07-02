"""Application assembly for the KNX emulator runtime."""

from __future__ import annotations

import asyncio
import logging
import shlex
from pathlib import Path

from .config import load_config
from .knx.bus import KnxBus
from .runtime.engine import RuntimeEngine


async def run_emulator(
    config_path: str | Path,
    *,
    gateway_ip: str,
    gateway_port: int = 3671,
    format_name: str | None = None,
    log_level: str = "INFO",
) -> None:
    """Run the virtual KNX device emulator until cancelled."""
    configure_logging(log_level)
    config = load_config(config_path, format_name=format_name)
    bus = KnxBus(gateway_ip=gateway_ip, gateway_port=gateway_port)
    engine = RuntimeEngine(config, bus)

    await engine.start()
    try:
        await bus.start()
        print(
            "Emulator started: "
            f"{len(engine.devices)} devices, "
            f"{engine.route_count} group addresses"
        )
        print("Local control is enabled. Type 'help' for commands.")
        await run_local_control(engine)
    finally:
        await engine.stop()
        await bus.stop()


def configure_logging(log_level: str) -> None:
    """Configure emulator logging."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


async def run_local_control(engine: RuntimeEngine) -> None:
    """Run a small stdin command interface for local device changes."""
    while True:
        try:
            line = await asyncio.to_thread(input, "knx-emulator> ")
        except EOFError:
            return

        command = line.strip()
        if not command:
            continue

        try:
            should_continue = await handle_local_command(engine, command)
        except ValueError as error:
            print(f"Error: {error}")
            continue

        if not should_continue:
            return


async def handle_local_command(
    engine: RuntimeEngine,
    command: str,
    *,
    echo: bool = True,
) -> bool:
    """Handle one local control command. Return False to stop the emulator."""
    parts = shlex.split(command)
    if not parts:
        return True

    action = parts[0].casefold()
    if action in {"quit", "exit"}:
        return False

    if action == "help":
        if echo:
            print(
                "Commands:\n"
                "  devices\n"
                "  state\n"
                "  set <device-name-or-id> <characteristic> <value>\n"
                "  quit\n\n"
                "Examples:\n"
                "  set Thermostat TargetTemperature 23.5\n"
                "  set \"Room AC\" OnOff true\n"
                "  set \"Room AC\" RotationSpeed 75"
            )
        return True

    if action == "devices":
        if echo:
            print("\n".join(engine.list_devices()))
        return True

    if action == "state":
        if echo:
            print("\n".join(engine.list_state()))
        return True

    if action == "set":
        if len(parts) != 4:
            raise ValueError(
                "Usage: set <device-name-or-id> <characteristic> <value>"
            )
        await engine.set_local_value(parts[1], parts[2], parts[3])
        if echo:
            print(f"OK: {parts[1]} {parts[2]} = {parts[3]}")
        return True

    raise ValueError(f"Unknown command: {parts[0]}")
