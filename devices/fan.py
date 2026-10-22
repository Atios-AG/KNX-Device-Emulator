"""Virtual step fan: the speed is a step number, not a percentage.

Unlike the fan built into the air conditioner (0..100 %, DPT 5.001), this
device is controlled by a plain speed step number sent as a single byte
(DPT 5.010, 0..255) to one group address. The number of steps is
configurable (1..4); step 0 always means "off". A value above the last
step is discarded: from the bus it is ignored (a warning in the log),
from the panel the command fails. An optional on/off object, like a fan
actuator's, switches to step 0 and back to the last step; its status is
sent when the fan starts or stops and in reply to its own command.

Config:
    [fan_bathroom]
    type      = fan
    ActionFan = 1/5/1     ; set the speed step (one byte, DPT 5.010)
    StatusFan = 2/5/1     ; step status (optional — remove to disable)
    Speeds    = 3         ; number of speed steps, 1..4 (4 by default)
    Speed     = 0         ; initial step (optional, 0 = off)
    ActionOn  = 1/5/2     ; optional, on/off (DPT 1.001): off = step 0, on = the last step
    StatusOn  = 2/5/2     ; optional, on/off status (DPT 1.001)
"""

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL, DPT_UCOUNT
from core.exceptions import CommandArgumentError, InvalidValueError


class FanDevice(BaseDevice):
    TYPE = "fan"

    MAX_SPEEDS = 4

    def setup(self) -> None:
        self._speeds = self.config.get_int("Speeds", self.MAX_SPEEDS)
        if not 1 <= self._speeds <= self.MAX_SPEEDS:
            raise InvalidValueError(
                f"[{self.config.section_name}] Speeds: "
                f"expected 1..{self.MAX_SPEEDS}, got {self._speeds}"
            )
        self._speed = self.config.get_int("Speed", 0)
        if not self._is_valid(self._speed):
            raise InvalidValueError(
                f"[{self.config.section_name}] Speed: "
                f"expected 0..{self._speeds}, got {self._speed}"
            )

        #: the step an on command resumes
        self._last = self._speed or self._speeds

        self.action_fan = self.add(
            ActionPoint("a_fan", self.config.get_ga("ActionFan"), DPT_UCOUNT, self.on_speed)
        )
        self.status_fan = None
        if "StatusFan" in self.config:
            self.status_fan = self.add(
                StatusPoint("speed", self.config.get_ga("StatusFan"), DPT_UCOUNT, lambda: self._speed)
            )
        if "ActionOn" in self.config:
            self.add(
                ActionPoint("a_on", self.config.get_ga("ActionOn"), DPT_BOOL, self.on_switch)
            )
        self.status_on: StatusPoint | None = None
        if "StatusOn" in self.config:
            self.status_on = self.add(
                StatusPoint("on", self.config.get_ga("StatusOn"), DPT_BOOL, lambda: self._speed > 0)
            )

    # --- bus -----------------------------------------------------------------
    def on_speed(self, value: int) -> None:
        if not self._is_valid(value):
            self.log.warning(
                "speed %r is out of 0..%d — discarded", value, self._speeds
            )
            return
        self._set_speed(int(value))

    def on_switch(self, value: bool) -> None:
        self._set_speed(self._last if value else 0, echo_on=True)

    # --- local commands ------------------------------------------------------
    @local_command("set_speed", description="Speed step 0..Speeds (0 = off)", args_schema={"speed": int})
    def cmd_set_speed(self, speed: int) -> dict:
        if not self._is_valid(speed):
            raise CommandArgumentError(
                f"Command 'set_speed': speed must be 0..{self._speeds}"
            )
        self._set_speed(speed)
        return {"speed": self._speed}

    @local_command("set", description="Switch on (the last step) or off", args_schema={"on": bool})
    def cmd_set(self, on: bool) -> dict:
        self._set_speed(self._last if on else 0)
        return self.state_snapshot()

    @local_command("off", description="Switch the fan off (step 0)")
    def cmd_off(self) -> dict:
        self._set_speed(0)
        return {"speed": self._speed}

    # --- logic ---------------------------------------------------------------
    def _set_speed(self, value: int, echo_on: bool = False) -> None:
        switched = (value > 0) != (self._speed > 0)
        self._speed = value
        if value:
            self._last = value
        if self.status_fan is not None:
            self.publish(self.status_fan)
        if self.status_on is not None and (switched or echo_on):
            self.publish(self.status_on)

    def _is_valid(self, value) -> bool:
        return 0 <= int(value) <= self._speeds
