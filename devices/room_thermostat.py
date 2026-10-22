"""Virtual KNX room thermostat / HVAC controller with a configurable mode object.

Built from the objects common KNX room controllers (MDT, Gira, ABB) and AC
gateways (Intesis) expose. Every object is optional, active when the group
address is set.

Command objects:
  * `ActionSetpoint` : DPT 9.001, setpoint in °C.
  * `ActionOnOff`    : DPT 1.001, power.
  * `ActionMode`     : one byte with the values `ModeOff` / `ModeHeat` /
                       `ModeCool` / `ModeAuto` (DPT 20.102, 20.105 or a vendor
                       coding), or with `ModeBit = True` a DPT 1.001 on/off.

Status objects:
  * `StatusSetpoint` : DPT 9.001.
  * `StatusCurrent`  : DPT 9.001, room temperature.
  * `StatusOnOff`    : DPT 1.001.
  * `StatusMode`     : the mode byte; without an on/off object the off byte
                       while off; with `ModeBit` the power.
  * `StatusSeason`   : DPT 1.100 heating/cooling switchover, 1 = heating
                       (winter); `SeasonInverted = True` flips the bit.

A mode byte sets the mode and the off byte switches off. Without an on/off
object a mode byte also switches on; with one, power follows the on/off object
only, like an AC gateway. The season sets the direction of a heat or cool mode
and is changed from the panel only. A status is sent when its value changes
and in reply to its own command. Local commands: `set_onoff` (on=), `set_mode`
(mode=off/heat/cool/auto), `set_setpoint` (value=), `set_current` (value=),
`set_season` (season=summer/winter).

Config:
    [thermostat_living]
    type           = room_thermostat
    ActionSetpoint = 1/4/1     ; optional, setpoint (DPT 9.001)
    StatusSetpoint = 1/4/2     ; optional, setpoint status (DPT 9.001)
    StatusCurrent  = 1/4/3     ; optional, room temperature (DPT 9.001)
    ActionOnOff    = 1/4/4     ; optional, power (DPT 1.001)
    StatusOnOff    = 1/4/5     ; optional, power status (DPT 1.001)
    ActionMode     = 1/4/6     ; optional, mode byte (or bit with ModeBit)
    StatusMode     = 1/4/7     ; optional, mode status
    StatusSeason   = 1/4/8     ; optional, heating/cooling (DPT 1.100)
    ModeOff        = 6         ; optional, leave out for a mode without an off value
    ModeHeat       = 1
    ModeCool       = 3
    ModeAuto       = 0         ; optional
    ModeBit        = False     ; True: the mode objects are a 1.001 on/off
    SeasonInverted = False     ; True: 1 = cooling (summer)
    Mode           = heat      ; initial mode: heat / cool / auto
    On             = True      ; initial power
    Setpoint       = 21.0      ; initial setpoint, °C
    Current        = 20.0      ; initial room temperature, °C
    Season         = winter    ; initial season: summer / winter
"""

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL, DPT_TEMPERATURE, DPT_UCOUNT
from core.exceptions import CommandArgumentError, InvalidValueError

_MODES = ("heat", "cool", "auto")
_SEASONS = ("summer", "winter")


class RoomThermostatDevice(BaseDevice):
    TYPE = "room_thermostat"

    def setup(self) -> None:
        self._bit = self.config.get_bool("ModeBit", False)
        #: the byte of each configured mode ("off" only with ModeOff)
        self._bytes = {
            m: self.config.get_int(f"Mode{m.title()}")
            for m in ("off",) + _MODES if f"Mode{m.title()}" in self.config
        }
        if not self._bit and len(set(self._bytes.values())) != len(self._bytes):
            raise InvalidValueError(
                f"[{self.config.section_name}] ModeOff/ModeHeat/ModeCool/ModeAuto: "
                f"two modes share one byte {self._bytes}"
            )
        self._mode = (self.config.get("Mode") or "heat").lower()
        if self._mode not in _MODES or (
            not self._bit and "ActionMode" in self.config and self._mode not in self._bytes
        ):
            raise InvalidValueError(
                f"[{self.config.section_name}] Mode: expected one of {_MODES} with a mode byte, "
                f"got '{self._mode}'"
            )
        self._season = (self.config.get("Season") or "winter").lower()
        if self._season not in _SEASONS:
            raise InvalidValueError(
                f"[{self.config.section_name}] Season: expected one of {_SEASONS}, got '{self._season}'"
            )
        self._season_inverted = self.config.get_bool("SeasonInverted", False)
        self._on = self.config.get_bool("On", True)
        self._setpoint = self.config.get_float("Setpoint", 21.0)
        self._current = self.config.get_float("Current", 20.0)
        #: with an on/off object power is separate from the mode
        self._power_object = "ActionOnOff" in self.config or "StatusOnOff" in self.config
        mode_dpt = DPT_BOOL if self._bit else DPT_UCOUNT

        if "ActionSetpoint" in self.config:
            self.add(
                ActionPoint("a_setpoint", self.config.get_ga("ActionSetpoint"), DPT_TEMPERATURE, self.on_setpoint)
            )
        self.status_setpoint: StatusPoint | None = None
        if "StatusSetpoint" in self.config:
            self.status_setpoint = self.add(
                StatusPoint("setpoint", self.config.get_ga("StatusSetpoint"), DPT_TEMPERATURE, lambda: self._setpoint)
            )
        if "StatusCurrent" in self.config:
            self.add(
                StatusPoint("current", self.config.get_ga("StatusCurrent"), DPT_TEMPERATURE, lambda: self._current)
            )
        if "ActionOnOff" in self.config:
            self.add(ActionPoint("a_onoff", self.config.get_ga("ActionOnOff"), DPT_BOOL, self.on_onoff))
        self.status_onoff: StatusPoint | None = None
        if "StatusOnOff" in self.config:
            self.status_onoff = self.add(
                StatusPoint("on", self.config.get_ga("StatusOnOff"), DPT_BOOL, lambda: self._on)
            )
        if "ActionMode" in self.config:
            self.add(ActionPoint("a_mode", self.config.get_ga("ActionMode"), mode_dpt, self.on_mode))
        self.status_mode: StatusPoint | None = None
        if "StatusMode" in self.config:
            self.status_mode = self.add(
                StatusPoint("mode", self.config.get_ga("StatusMode"), mode_dpt, self._mode_status)
            )
        if "StatusSeason" in self.config:
            self.add(
                StatusPoint(
                    "season", self.config.get_ga("StatusSeason"), DPT_BOOL,
                    lambda: (self._season == "winter") != self._season_inverted,
                )
            )

    def _mode_status(self):
        if self._bit:
            return self._on
        if not self._on and not self._power_object and "off" in self._bytes:
            return self._bytes["off"]
        return self._bytes.get(self._mode, 0)

    # --- bus -----------------------------------------------------------------
    def on_setpoint(self, value: float) -> None:
        self._change(echo=self.status_setpoint, setpoint=float(value))

    def on_onoff(self, value: bool) -> None:
        self._change(echo=self.status_onoff, on=bool(value))

    def on_mode(self, value) -> None:
        if self._bit:
            self._change(echo=self.status_mode, on=bool(value))
            return
        mode = next((m for m, b in self._bytes.items() if b == int(value)), None)
        if mode is None:
            self.log.warning("mode byte %r is not configured, ignored", value)
            self._change(echo=self.status_mode)
        elif mode == "off":
            self._change(echo=self.status_mode, on=False)
        elif self._power_object:
            self._change(echo=self.status_mode, mode=mode)
        else:
            self._change(echo=self.status_mode, mode=mode, on=True)

    # --- local commands (panel) ----------------------------------------------
    @local_command("set_onoff", description="Switch on/off", args_schema={"on": bool})
    def cmd_set_onoff(self, on: bool) -> dict:
        return self._change(on=on)

    @local_command("set_mode", description="off, or switch on in heat/cool/auto", args_schema={"mode": str})
    def cmd_set_mode(self, mode: str) -> dict:
        mode = mode.lower()
        if mode == "off":
            return self._change(on=False)
        if mode not in _MODES:
            raise CommandArgumentError(f"Command 'set_mode': mode must be off or one of {_MODES}")
        return self._change(mode=mode, on=True)

    @local_command("set_setpoint", description="Setpoint, °C", args_schema={"value": float})
    def cmd_set_setpoint(self, value: float) -> dict:
        return self._change(setpoint=value)

    @local_command("set_current", description="Room temperature, °C", args_schema={"value": float})
    def cmd_set_current(self, value: float) -> dict:
        return self._change(current=value)

    @local_command("set_season", description="summer or winter", args_schema={"season": str})
    def cmd_set_season(self, season: str) -> dict:
        season = season.lower()
        if season not in _SEASONS:
            raise CommandArgumentError(f"Command 'set_season': season must be one of {_SEASONS}")
        mode = self._mode
        if mode in ("heat", "cool"):
            mode = "heat" if season == "winter" else "cool"
        return self._change(season=season, mode=mode)

    # --- logic ---------------------------------------------------------------
    def _change(self, echo: StatusPoint | None = None, **state) -> dict:
        """Apply the new state, then send every status that changed and the echo."""
        statuses = [dp for dp in self.datapoints if isinstance(dp, StatusPoint)]
        before = {dp: dp.read() for dp in statuses}
        for key, value in state.items():
            setattr(self, f"_{key}", value)
        for dp, old in before.items():
            if dp is echo or dp.read() != old:
                self.publish(dp)
        return self.state_snapshot()

    def state_snapshot(self) -> dict:
        return {"on": self._on, "mode": self._mode, "setpoint": self._setpoint,
                "current": self._current, "season": self._season}
