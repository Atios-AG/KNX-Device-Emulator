"""Virtual thermostat / air conditioner.

Elements of the device:
  * Target temperature    — Control + Status (DPT 9.001)
  * Current temperature   — Status           (DPT 9.001)
  * Target mode           — Control          (DPT 20.105: off/heat/cool/auto)
  * Current mode          — Status           (DPT 20.105) — mirrors the target
  * On/Off                — Control + Status (DPT 1.001)
  * Summer/Winter         — Status, changed from the panel only (DPT 1.100),
                            optional

Logic (agreed with the customer):
  1. The target mode is Control only, there is no separate status for it.
  2. On/Off and the target mode are EQUIVALENT: on == (mode != off). Either
     command (On/Off=off OR mode=off) switches the device off; (On/Off=on OR
     mode=heat/cool/auto) switches it on.
  3. The current mode simply mirrors the target one, without regard to the
     temperature (in auto it is exactly auto that goes on the bus, not the
     direction the device has picked).
  4. Summer/Winter is an internal state, changed ONLY from the panel. Summer ->
     only cool is possible, Winter -> only heat. A command with an incompatible
     mode from the bus/panel is ignored; changing the season while an
     incompatible mode is active switches the device off.
  5. AUTO (option 4 in 20.105) — the device decides on its own whether to heat
     or to cool by comparing the current temperature with the target one (with
     the AutoHysteresis hysteresis). Auto is available ONLY when the seasonal
     mode is not activated (there is no StatusSeason in the config): with a
     season set, the direction is already fixed by the season.

All the non-standard DPTs are defined right here — the core of the project
stays untouched.
"""

from __future__ import annotations

import asyncio
import logging

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT, DPT_BOOL, DPT_TEMPERATURE
from core.exceptions import CommandArgumentError, CommandError, DPTError

log = logging.getLogger(__name__)

_MODES = ("off", "heat", "cool", "auto")
_SEASONS = ("summer", "winter")


# --- local DPTs (they live in the device module, the core is untouched) ------
class DPTHvacMode(DPT):
    """20.105 HVAC Control Mode. On the Python side — off/heat/cool/auto strings."""

    main, sub = 20, 105
    payload_kind = "array"
    _TO_RAW = {"off": 1, "heat": 2, "cool": 3, "auto": 4}
    _FROM_RAW = {v: k for k, v in _TO_RAW.items()}

    def encode(self, value) -> bytes:
        if value not in self._TO_RAW:
            raise DPTError(f"20.105: expected {_MODES}, got {value!r}")
        return bytes([self._TO_RAW[value]])

    def decode(self, raw) -> str:
        byte = raw[0] if isinstance(raw, (bytes, bytearray)) else int(raw)
        return self._FROM_RAW.get(byte, "off")


class DPTHeatCool(DPT):
    """1.100 DPT_Heat/Cool: 0=cooling (summer), 1=heating (winter)."""

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
        # the dead band of the auto mode: while |current - setpoint| stays
        # inside it, the device does nothing (otherwise it would flip
        # heat<->cool)
        self._auto_hyst = abs(float(self.config.get("AutoHysteresis", 0.5)))
        # what auto has chosen right now: 'heat' | 'cool' | None (inside the band)
        self._auto_action = None

        # --- season (optional) ---------------------------------------------
        self._season_enabled = "StatusSeason" in self.config
        self._season = None
        if self._season_enabled:
            season = (self.config.get("Season") or "winter").lower()
            if season not in _SEASONS:
                raise CommandArgumentError(f"Season must be one of {_SEASONS}")
            self._season = season

        # --- initial mode / power -------------------------------------------
        mode = (self.config.get("Mode") or "off").lower()
        if mode not in _MODES:
            raise CommandArgumentError(f"Mode must be one of {_MODES}")
        if mode != "off" and not self._season_allows(mode):
            log.warning(
                "%s: the initial mode '%s' is incompatible with the season '%s' — starting switched off",
                self.name, mode, self._season,
            )
            mode = "off"
        self._mode = mode
        self._on = mode != "off"
        self._last_active_mode = mode if mode != "off" else self._default_active_mode()
        self._update_auto_action()

        # --- data points -----------------------------------------------------
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
        # the target mode is Control only (no status, item 1)
        self.action_mode = self.add(
            ActionPoint("a_mode", self.config.get_ga("ActionMode"), DPT_HVAC_MODE, self.on_mode)
        )
        # the current mode is a Status, it mirrors the target one (item 3)
        self.status_mode = self.add(
            StatusPoint("mode", self.config.get_ga("StatusMode"), DPT_HVAC_MODE, lambda: self._mode)
        )
        if self._season_enabled:
            self.status_season = self.add(
                StatusPoint("season", self.config.get_ga("StatusSeason"), DPT_HEAT_COOL, lambda: self._season)
            )

    # --- commands from the bus ----------------------------------------------
    def on_onoff(self, value: bool) -> None:
        self._set_onoff(bool(value))

    def on_setpoint(self, value: float) -> None:
        self._set_setpoint(value)

    def on_mode(self, value: str) -> None:
        self._set_mode(value)

    # --- local commands (panel) ----------------------------------------------
    @local_command("set_onoff", description="Switch on/off", args_schema={"on": bool})
    def cmd_set_onoff(self, on: bool) -> dict:
        self._set_onoff(on)
        return self.state_snapshot()

    @local_command("set_mode", description="Target mode: off/heat/cool/auto", args_schema={"mode": str})
    def cmd_set_mode(self, mode: str) -> dict:
        mode = mode.lower()
        if mode not in _MODES:
            raise CommandArgumentError(f"mode must be one of {_MODES}")
        self._set_mode(mode)
        return self.state_snapshot()

    @local_command("set_setpoint", description="Target temperature", args_schema={"value": float})
    def cmd_set_setpoint(self, value: float) -> dict:
        self._set_setpoint(value)
        return self.state_snapshot()

    @local_command("set_current", description="Current temperature (sensor simulation)", args_schema={"value": float})
    def cmd_set_current(self, value: float) -> dict:
        self._current = float(value)
        self._update_auto_action()
        self.publish(self.status_current)
        return self.state_snapshot()

    @local_command("set_season", description="Summer/Winter (from the panel only)", args_schema={"season": str})
    def cmd_set_season(self, season: str) -> dict:
        if not self._season_enabled:
            raise CommandError("The seasonal mode is disabled in the config (no StatusSeason)")
        season = season.lower()
        if season not in _SEASONS:
            raise CommandArgumentError(f"season must be one of {_SEASONS}")
        self._set_season(season)
        return self.state_snapshot()

    # --- core of the logic ---------------------------------------------------
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
            if mode == "auto":
                log.warning(
                    "%s: the 'auto' mode is unavailable while the seasonal mode is active "
                    "(the season '%s' sets the direction itself) — the command is ignored",
                    self.name, self._season,
                )
            else:
                log.warning(
                    "%s: the mode '%s' is unavailable in the season '%s' — the command is ignored",
                    self.name, mode, self._season,
                )
            return
        self._activate(mode)

    def _set_setpoint(self, value: float) -> None:
        self._setpoint = float(value)
        self._update_auto_action()
        self.publish(self.status_setpoint)

    def _set_season(self, season: str) -> None:
        self._season = season
        self.publish(self.status_season)
        self._last_active_mode = self._default_active_mode()
        # the active mode has become incompatible with the season -> switch off
        # (item 4)
        if self._mode != "off" and not self._season_allows(self._mode):
            log.info("%s: the season change to '%s' switches the device off", self.name, season)
            self._deactivate()

    def _activate(self, mode: str) -> None:
        self._mode = mode
        self._on = True
        self._last_active_mode = mode
        self._auto_action = None  # the auto decision is taken anew
        self._update_auto_action()
        self._publish_power_state()

    def _deactivate(self) -> None:
        self._mode = "off"
        self._on = False
        self._auto_action = None
        self._publish_power_state()

    def _publish_power_state(self) -> None:
        # on/off and mode change together, so we broadcast both statuses
        self.publish(self.status_onoff)
        self.publish(self.status_mode)

    # --- season --------------------------------------------------------------
    def _season_allows(self, mode: str) -> bool:
        # auto is only possible while the seasonal mode is inactive (item 5):
        # the season already fixes the direction, there is nothing left for the
        # device to choose
        if self._season == "summer":
            return mode == "cool"
        if self._season == "winter":
            return mode == "heat"
        return True  # the season is disabled — both directions and auto are available

    def _default_active_mode(self) -> str:
        if self._season == "summer":
            return "cool"
        if self._season == "winter":
            return "heat"
        return "heat"

    # --- auto: the device chooses the direction itself -----------------------
    def _update_auto_action(self) -> str | None:
        """Recompute whether to heat or to cool right now (in auto mode only).

        Hysteresis: leaving the dead band requires a deviation larger than
        AutoHysteresis, while a heating/cooling that has started runs up to the
        setpoint.
        """
        if self._mode != "auto":
            self._auto_action = None
            return None

        prev = self._auto_action
        action = prev
        # an action that has started is continued up to the target temperature...
        if action == "heat" and self._current >= self._setpoint:
            action = None
        elif action == "cool" and self._current <= self._setpoint:
            action = None
        # ...while idling is left only outside the dead band
        if action is None:
            if self._current < self._setpoint - self._auto_hyst:
                action = "heat"
            elif self._current > self._setpoint + self._auto_hyst:
                action = "cool"

        if action != prev:
            log.info(
                "%s: auto — %s (current %.1f, target %.1f)",
                self.name,
                {"heat": "heating", "cool": "cooling", None: "within the comfort band, idle"}[action],
                self._current, self._setpoint,
            )
        self._auto_action = action
        return action

    def _effective_action(self) -> str | None:
        """What the device physically does: 'heat' | 'cool' | None."""
        if self._mode == "auto":
            return self._update_auto_action()
        return self._mode if self._mode in ("heat", "cool") else None

    def state_snapshot(self) -> dict:
        snapshot = super().state_snapshot()
        if self._mode == "auto":
            # the direction chosen by auto does not go on the bus (the mode
            # there is auto), but it is useful for a panel to see what the
            # device is doing
            snapshot["auto_action"] = self._auto_action
        return snapshot

    # --- background physics simulation ---------------------------------------
    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._cycle)
            self._tick()

    def _tick(self) -> None:
        """One simulation step: move the temperature and broadcast the status."""
        action = self._effective_action()
        if action == "heat" and self._current < self._setpoint:
            self._current = min(self._setpoint, self._current + 0.5)
        elif action == "cool" and self._current > self._setpoint:
            self._current = max(self._setpoint, self._current - 0.5)
        self._update_auto_action()  # the temperature changed — the decision may be stale
        self.publish(self.status_current)
