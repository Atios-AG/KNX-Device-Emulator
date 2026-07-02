"""Виртуальный термостат / кондиционер.

Элементы устройства:
  * Целевая температура   — Control + Status (DPT 9.001)
  * Текущая температура   — Status          (DPT 9.001)
  * Целевой режим         — Control         (DPT 20.105: off/heat/cool)
  * Текущий режим         — Status          (DPT 20.105) — зеркалит целевой
  * Он/Офф                — Control + Status (DPT 1.001)
  * Лето/Зима             — Status, смена только с панели (DPT 1.100), опционально

Логика (согласовано с заказчиком):
  1. Целевой режим — только Control, отдельного статуса нет.
  2. On/Off и целевой режим РАВНОЦЕННЫ: on == (mode != off). Любая из команд
     (On/Off=off ИЛИ mode=off) выключает; (On/Off=on ИЛИ mode=heat/cool) включает.
  3. Текущий режим просто зеркалит целевой, без учёта температуры.
  4. Лето/Зима — внутреннее состояние, меняется ТОЛЬКО с панели. Лето → можно
     только cool, Зима → только heat. Команда несовместимого режима с шины/панели
     игнорируется; смена сезона при активном несовместимом режиме выключает прибор.

Все нестандартные DPT определены здесь же — ядро проекта не меняется.
"""

from __future__ import annotations

import asyncio
import logging

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT, DPT_BOOL, DPT_TEMPERATURE
from core.exceptions import CommandArgumentError, CommandError, DPTError

log = logging.getLogger(__name__)

_MODES = ("off", "heat", "cool")
_SEASONS = ("summer", "winter")


# --- локальные DPT (живут в модуле устройства, ядро не трогаем) --------------
class DPTHvacMode(DPT):
    """20.105 HVAC Control Mode. На питон-стороне — строки off/heat/cool."""

    main, sub = 20, 105
    payload_kind = "array"
    _TO_RAW = {"off": 1, "heat": 2, "cool": 3}
    _FROM_RAW = {v: k for k, v in _TO_RAW.items()}

    def encode(self, value) -> bytes:
        if value not in self._TO_RAW:
            raise DPTError(f"20.105: ожидался {_MODES}, получено {value!r}")
        return bytes([self._TO_RAW[value]])

    def decode(self, raw) -> str:
        byte = raw[0] if isinstance(raw, (bytes, bytearray)) else int(raw)
        return self._FROM_RAW.get(byte, "off")


class DPTHeatCool(DPT):
    """1.100 DPT_Heat/Cool: 0=cooling(лето), 1=heating(зима)."""

    main, sub = 1, 100
    payload_kind = "binary"

    def encode(self, value) -> int:
        return 1 if value == "winter" else 0

    def decode(self, raw) -> str:
        return "winter" if int(raw) else "summer"


DPT_HVAC_MODE = DPTHvacMode()
DPT_HEAT_COOL = DPTHeatCool()


class ThermostatDevice(BaseDevice):
    TYPE = "thermostat"

    def setup(self) -> None:
        self._setpoint = float(self.config.get("Setpoint", 21.0))
        self._current = float(self.config.get("Current", 20.0))
        self._cycle = self.config.get_int("CycleSec", 30)
        self._task = None

        # --- сезон (опционально) -------------------------------------------
        self._season_enabled = "StatusSeason" in self.config
        self._season = None
        if self._season_enabled:
            season = (self.config.get("Season") or "winter").lower()
            if season not in _SEASONS:
                raise CommandArgumentError(f"Season должен быть {_SEASONS}")
            self._season = season

        # --- начальный режим / питание -------------------------------------
        mode = (self.config.get("Mode") or "off").lower()
        if mode not in _MODES:
            raise CommandArgumentError(f"Mode должен быть {_MODES}")
        if mode != "off" and not self._season_allows(mode):
            mode = "off"
        self._mode = mode
        self._on = mode != "off"
        self._last_active_mode = self._default_active_mode()

        # --- точки данных ---------------------------------------------------
        self.action_onoff = self.add(
            ActionPoint("a_onoff", self.config.get_ga("ActionOnOff"), DPT_BOOL, self.on_onoff)
        )
        self.status_onoff = self.add(
            StatusPoint("on", self.config.get_ga("StatusOnOff"), DPT_BOOL, lambda: self._on)
        )
        self.action_setpoint = self.add(
            ActionPoint("a_setpoint", self.config.get_ga("ActionSetpoint"), DPT_TEMPERATURE, self.on_setpoint)
        )
        self.status_setpoint = self.add(
            StatusPoint("setpoint", self.config.get_ga("StatusSetpoint"), DPT_TEMPERATURE, lambda: self._setpoint)
        )
        self.status_current = self.add(
            StatusPoint("current", self.config.get_ga("StatusCurrent"), DPT_TEMPERATURE, lambda: round(self._current, 1))
        )
        # целевой режим — только Control (без статуса, п.1)
        self.action_mode = self.add(
            ActionPoint("a_mode", self.config.get_ga("ActionMode"), DPT_HVAC_MODE, self.on_mode)
        )
        # текущий режим — Status, зеркалит целевой (п.3)
        self.status_mode = self.add(
            StatusPoint("mode", self.config.get_ga("StatusMode"), DPT_HVAC_MODE, lambda: self._mode)
        )
        if self._season_enabled:
            self.status_season = self.add(
                StatusPoint("season", self.config.get_ga("StatusSeason"), DPT_HEAT_COOL, lambda: self._season)
            )

    # --- команды с шины -----------------------------------------------------
    def on_onoff(self, value: bool) -> None:
        self._set_onoff(bool(value))

    def on_setpoint(self, value: float) -> None:
        self._set_setpoint(value)

    def on_mode(self, value: str) -> None:
        self._set_mode(value)

    # --- локальные команды (панель) -----------------------------------------
    @local_command("set_onoff", description="Включить/выключить", args_schema={"on": bool})
    def cmd_set_onoff(self, on: bool) -> dict:
        self._set_onoff(on)
        return self.state_snapshot()

    @local_command("set_mode", description="Целевой режим: off/heat/cool", args_schema={"mode": str})
    def cmd_set_mode(self, mode: str) -> dict:
        mode = mode.lower()
        if mode not in _MODES:
            raise CommandArgumentError(f"mode должен быть {_MODES}")
        self._set_mode(mode)
        return self.state_snapshot()

    @local_command("set_setpoint", description="Целевая температура", args_schema={"value": float})
    def cmd_set_setpoint(self, value: float) -> dict:
        self._set_setpoint(value)
        return self.state_snapshot()

    @local_command("set_current", description="Текущая температура (имитация датчика)", args_schema={"value": float})
    def cmd_set_current(self, value: float) -> dict:
        self._current = float(value)
        self.publish(self.status_current)
        return self.state_snapshot()

    @local_command("set_season", description="Лето/Зима (только с панели)", args_schema={"season": str})
    def cmd_set_season(self, season: str) -> dict:
        if not self._season_enabled:
            raise CommandError("Сезонный режим отключён в конфиге (нет StatusSeason)")
        season = season.lower()
        if season not in _SEASONS:
            raise CommandArgumentError(f"season должен быть {_SEASONS}")
        self._set_season(season)
        return self.state_snapshot()

    # --- ядро логики --------------------------------------------------------
    def _set_onoff(self, on: bool) -> None:
        if on:
            if self._mode == "off":
                self._activate(self._last_active_mode)
        else:
            self._deactivate()

    def _set_mode(self, mode: str) -> None:
        if mode == "off":
            self._deactivate()
            return
        if not self._season_allows(mode):
            log.warning(
                "%s: режим '%s' недоступен в сезоне '%s' — команда проигнорирована",
                self.name, mode, self._season,
            )
            return
        self._activate(mode)

    def _set_setpoint(self, value: float) -> None:
        self._setpoint = float(value)
        self.publish(self.status_setpoint)

    def _set_season(self, season: str) -> None:
        self._season = season
        self.publish(self.status_season)
        self._last_active_mode = self._default_active_mode()
        # активный режим стал несовместим с сезоном -> выключаемся (п.4)
        if self._mode != "off" and not self._season_allows(self._mode):
            log.info("%s: смена сезона на '%s' выключает прибор", self.name, season)
            self._deactivate()

    def _activate(self, mode: str) -> None:
        self._mode = mode
        self._on = True
        self._last_active_mode = mode
        self._publish_power_state()

    def _deactivate(self) -> None:
        self._mode = "off"
        self._on = False
        self._publish_power_state()

    def _publish_power_state(self) -> None:
        # on/off и mode меняются вместе, поэтому рассылаем оба статуса
        self.publish(self.status_onoff)
        self.publish(self.status_mode)

    # --- сезон --------------------------------------------------------------
    def _season_allows(self, mode: str) -> bool:
        if self._season == "summer":
            return mode == "cool"
        if self._season == "winter":
            return mode == "heat"
        return True  # сезон отключён — оба направления доступны

    def _default_active_mode(self) -> str:
        if self._season == "summer":
            return "cool"
        if self._season == "winter":
            return "heat"
        return "heat"

    # --- фоновая имитация физики --------------------------------------------
    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._cycle)
            if self._mode == "heat" and self._current < self._setpoint:
                self._current = min(self._setpoint, self._current + 0.5)
            elif self._mode == "cool" and self._current > self._setpoint:
                self._current = max(self._setpoint, self._current - 0.5)
            self.publish(self.status_current)
