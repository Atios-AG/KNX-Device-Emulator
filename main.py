"""Entry point of the KNX virtual device simulator.

Wires the components together: config -> plugin registry -> bus -> device
manager -> control interface. No business logic lives here.

Run with:
    python main.py --config config.ini
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import threading

from core.bus_adapter import KNXIPBusAdapter
from core.config_loader import ConfigLoader
from core.control.interface import ControlInterface
from core.control.transports import create_transport
from core.device_manager import DeviceManager
from core.exceptions import ConfigError, KnxSimError
from core.registry import DeviceRegistry

log = logging.getLogger("knxsim")

DEFAULT_SHUTDOWN_TIMEOUT = 3.0


def _die(code: int = 130) -> None:
    """Terminate the process right now, without waiting for anything.

    Used when a graceful shutdown is not possible or takes too long: os._exit
    skips the atexit handlers and the asyncio finalisation (the very part
    that can hang on the KNX connection), so the logs are flushed by hand.
    """
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        logging.shutdown()
    finally:
        os._exit(code)


def _arm_watchdog(seconds: float, code: int = 130) -> threading.Timer:
    """Hard deadline for the shutdown.

    A daemon timer that kills the process if the graceful path (including the
    asyncio.run() finalisation and the terminal restore) has not finished in
    time. If everything ends normally the process exits earlier and the daemon
    timer simply dies with it.
    """
    timer = threading.Timer(
        seconds,
        lambda: (
            log.warning("Shutdown timed out (%.1f s) — terminating forcefully.", seconds),
            _die(code),
        ),
    )
    timer.daemon = True
    timer.start()
    return timer


async def run(config_path: str, shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT) -> None:
    config = ConfigLoader.load(config_path)

    registry = DeviceRegistry()
    registry.discover("devices")
    log.info("Available device types: %s", registry.types)

    bus = KNXIPBusAdapter(config.knx)
    manager = DeviceManager(registry, bus)
    manager.build(config)

    interface = ControlInterface(manager)
    transport = create_transport(
        config.control.get("transport", "rest"), interface, config.control
    )

    stop_event = asyncio.Event()
    transport.on_stop = stop_event.set  # the quit command in the CLI ends the app

    await bus.connect()
    await manager.start_all()
    await transport.start()

    def _on_signal(sig: signal.Signals) -> None:
        if stop_event.is_set():
            # the second Ctrl+C means "I am not waiting any longer"
            log.warning("Repeated %s — terminating immediately.", sig.name)
            _die()
        log.info(
            "Received %s — stopping (at most %.1f s, press Ctrl+C again to "
            "terminate immediately)...",
            sig.name, shutdown_timeout,
        )
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal, sig)
        except NotImplementedError:  # pragma: no cover (Windows)
            signal.signal(
                sig,
                lambda s, _frame: loop.call_soon_threadsafe(_on_signal, signal.Signals(s)),
            )

    log.info("Simulator started. Press Ctrl+C to stop.")
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass

    # From here on nothing may block the exit: the KNX disconnect (and any
    # device timer) gets a limited amount of time, after that the process is
    # killed anyway.
    # a bit later than wait_for below: the watchdog is the backstop that also
    # covers the asyncio.run() finalisation, not the primary limit
    _arm_watchdog(shutdown_timeout + 1.0, code=0)
    log.info("Stopping...")
    try:
        await asyncio.wait_for(
            _graceful_shutdown(transport, manager, bus), shutdown_timeout
        )
        log.info("Stopped.")
    except (asyncio.TimeoutError, TimeoutError):
        log.warning(
            "The KNX shutdown did not finish in %.1f s — exiting anyway.",
            shutdown_timeout,
        )
        _die(0)
    except Exception as exc:  # a broken connection must not block the exit
        log.warning("Error while stopping: %s — exiting anyway.", exc)
        _die(0)

    # the leftovers (xknx internals, transport tasks): cancel and do not wait
    # for them — asyncio.run() would otherwise await them without a limit
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending, timeout=0.5)

    # Everything we own has stopped. Leaving through asyncio.run() would still
    # block: its finalisation waits for the default executor (the blocking
    # stdin.readline of the CLI) and for the xknx internals. Nothing useful is
    # left to do, so the process ends right here.
    _die(0)


async def _graceful_shutdown(transport, manager, bus) -> None:
    """Best-effort ordered shutdown; each step is independent of the others."""
    # the factories are lazy: on a timeout the remaining steps must not be
    # created as coroutines that are never awaited
    for step, factory in (
        ("control transport", transport.stop),
        ("devices", manager.stop_all),
        ("KNX bus", bus.disconnect),
    ):
        try:
            await factory()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Failed to stop %s cleanly: %s", step, exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="KNX virtual device simulator")
    parser.add_argument("--config", "-c", default="config.ini", help="path to the ini config")
    parser.add_argument("--log-level", "-l", default="INFO")
    parser.add_argument(
        "--shutdown-timeout",
        type=float,
        default=DEFAULT_SHUTDOWN_TIMEOUT,
        help="seconds to wait for a graceful shutdown before the process is "
             f"killed anyway (default: {DEFAULT_SHUTDOWN_TIMEOUT:g})",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    timeout = max(0.1, args.shutdown_timeout)

    try:
        asyncio.run(run(args.config, timeout))
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        raise SystemExit(2)
    except KnxSimError as exc:
        log.error("Error: %s", exc)
        raise SystemExit(1)
    except KeyboardInterrupt:
        # Ctrl+C outside of the signal handler (start-up, Windows): do not let
        # the asyncio finalisation wait for the KNX connection
        _die(130)


if __name__ == "__main__":
    main()
