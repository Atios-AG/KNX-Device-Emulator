"""Virtual step fan: the speed is a step number, not a percentage.

Unlike the fan built into the air conditioner (0..100 %, DPT 5.001), this
device is controlled by a plain speed step number sent as a single byte
(DPT 5.010, 0..255) to one group address. The number of steps is
configurable (1..4); step 0 always means "off". A value above the last
step is discarded: from the bus it is ignored (a warning in the log),
from the panel the command fails.

Config:
    [fan_bathroom]
    type      = fan
    ActionFan = 1/5/1     ; set the speed step (one byte, DPT 5.010)
    StatusFan = 2/5/1     ; step status (optional — remove to disable)
    Speeds    = 3         ; number of speed steps, 1..4 (4 by default)
    Speed     = 0         ; initial step (optional, 0 = off)
"""

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_UCOUNT
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

        self.action_fan = self.add(
            ActionPoint("a_fan", self.config.get_ga("ActionFan"), DPT_UCOUNT, self.on_speed)
        )
        self.status_fan = None
        if "StatusFan" in self.config:
            self.status_fan = self.add(
                StatusPoint("speed", self.config.get_ga("StatusFan"), DPT_UCOUNT, lambda: self._speed)
            )

    # --- bus -----------------------------------------------------------------
    def on_speed(self, value: int) -> None:
        if not self._is_valid(value):
            self.log.warning(
                "speed %r is out of 0..%d — discarded", value, self._speeds
            )
            return
        self._set_speed(int(value))

    # --- local commands ------------------------------------------------------
    @local_command("set_speed", description="Speed step 0..Speeds (0 = off)", args_schema={"speed": int})
    def cmd_set_speed(self, speed: int) -> dict:
        if not self._is_valid(speed):
            raise CommandArgumentError(
                f"Command 'set_speed': speed must be 0..{self._speeds}"
            )
        self._set_speed(speed)
        return {"speed": self._speed}

    @local_command("off", description="Switch the fan off (step 0)")
    def cmd_off(self) -> dict:
        self._set_speed(0)
        return {"speed": self._speed}

    # --- logic ---------------------------------------------------------------
    def _set_speed(self, value: int) -> None:
        self._speed = value
        if self.status_fan is not None:
            self.publish(self.status_fan)

    def _is_valid(self, value) -> bool:
        return 0 <= int(value) <= self._speeds
