"""REST-транспорт управления (aiohttp).

Эндпоинты:
    GET  /devices                     -> список устройств с состоянием
    GET  /devices/{name}              -> состояние + доступные команды
    POST /devices/{name}/commands     -> выполнить команду
         тело: {"command": "set", "args": {"on": true}}

Импорт aiohttp ленивый, чтобы зависимость требовалась только при использовании.
"""

from __future__ import annotations

import logging

from ...exceptions import UnknownDeviceError
from ..command import Command
from .base import ControlTransport

log = logging.getLogger(__name__)


class RestTransport(ControlTransport):
    NAME = "rest"

    def __init__(self, interface, config):
        super().__init__(interface, config)
        self._runner = None

    async def start(self) -> None:
        from aiohttp import web

        app = web.Application()
        app.add_routes(
            [
                web.get("/devices", self._list),
                web.get("/devices/{name}", self._describe),
                web.post("/devices/{name}/commands", self._command),
            ]
        )
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        host = self.config.get("host", "0.0.0.0")
        port = int(self.config.get("port", 8080))
        site = web.TCPSite(self._runner, host, port)
        await site.start()
        log.info("REST интерфейс управления слушает http://%s:%s", host, port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()

    # --- обработчики ---------------------------------------------------------
    async def _list(self, request):
        from aiohttp import web

        return web.json_response(self.interface.list_devices())

    async def _describe(self, request):
        from aiohttp import web

        name = request.match_info["name"]
        try:
            return web.json_response(self.interface.describe_device(name))
        except UnknownDeviceError as exc:
            return web.json_response({"error": str(exc)}, status=404)

    async def _command(self, request):
        from aiohttp import web

        name = request.match_info["name"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "ожидался JSON"}, status=400)
        command = Command(
            device=name,
            name=body.get("command", ""),
            args=body.get("args", {}) or {},
        )
        result = self.interface.execute(command)
        status = 200 if result.ok else 400
        return web.json_response(result.to_dict(), status=status)
