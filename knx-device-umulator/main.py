"""Точка входа симулятора виртуальных устройств KNX.

Склейка компонентов: конфиг -> реестр плагинов -> шина -> менеджер устройств
-> интерфейс управления. Бизнес-логики здесь нет.

Запуск:
    python main.py --config config.ini
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from core.bus_adapter import KNXIPBusAdapter
from core.config_loader import ConfigLoader
from core.control.interface import ControlInterface
from core.control.transports import create_transport
from core.device_manager import DeviceManager
from core.exceptions import ConfigError, KnxSimError
from core.registry import DeviceRegistry

log = logging.getLogger("knxsim")


async def run(config_path: str) -> None:
    config = ConfigLoader.load(config_path)

    registry = DeviceRegistry()
    registry.discover("devices")
    log.info("Доступные типы устройств: %s", registry.types)

    bus = KNXIPBusAdapter(config.knx)
    manager = DeviceManager(registry, bus)
    manager.build(config)

    interface = ControlInterface(manager)
    transport = create_transport(
        config.control.get("transport", "rest"), interface, config.control
    )

    stop_event = asyncio.Event()
    transport.on_stop = stop_event.set  # команда quit в CLI завершит приложение

    await bus.connect()
    await manager.start_all()
    await transport.start()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover (Windows)
            pass

    log.info("Симулятор запущен. Ctrl+C для остановки.")
    await stop_event.wait()

    log.info("Остановка...")
    await transport.stop()
    await manager.stop_all()
    await bus.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Симулятор виртуальных устройств KNX")
    parser.add_argument("--config", "-c", default="config.ini", help="путь к ini-конфигу")
    parser.add_argument("--log-level", "-l", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    try:
        asyncio.run(run(args.config))
    except ConfigError as exc:
        log.error("Ошибка конфигурации: %s", exc)
        raise SystemExit(2)
    except KnxSimError as exc:
        log.error("Ошибка: %s", exc)
        raise SystemExit(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
