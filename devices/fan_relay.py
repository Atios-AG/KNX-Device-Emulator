"""Virtual multi-winding fan: one relay (group address) per speed.

Emulates a fan whose speed windings are switched by a relay actuator: every
speed step has its own on/off group address (DPT 1.001), one relay per
address. The fan is passive — it only mirrors the relay commands into the
winding states and never switches anything off by itself.

Its job is to *verify* the actuator's switching algorithm: on a speed
change the actuator must first switch OFF all the windings and only then
switch ON the needed one (break-before-make). Violations are written to
the log as errors:

  * a winding is switched on while another winding is still energized;
  * on a speed change the actuator did not send OFF to every winding
    before sending the ON.

Config:
    [fan_ceiling]
    type         = fan_relay
    Speeds       = 3          ; number of speed steps, 1..4 (4 by default)
    ActionSpeed1 = 1/6/1      ; relay of the speed-1 winding (DPT 1.001)
    StatusSpeed1 = 2/6/1      ; winding status (optional — remove to disable)
    ActionSpeed2 = 1/6/2
    StatusSpeed2 = 2/6/2
    ActionSpeed3 = 1/6/3
    StatusSpeed3 = 2/6/3
    Speed        = 0          ; initial step (optional, 0 = off)
"""

from functools import partial

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL
from core.exceptions import CommandArgumentError, InvalidValueError


class RelayFanDevice(BaseDevice):
    TYPE = "fan_relay"

    MAX_SPEEDS = 4

    def setup(self) -> None:
        self._speeds = self.config.get_int("Speeds", self.MAX_SPEEDS)
        if not 1 <= self._speeds <= self.MAX_SPEEDS:
            raise InvalidValueError(
                f"[{self.config.section_name}] Speeds: "
                f"expected 1..{self.MAX_SPEEDS}, got {self._speeds}"
            )
        initial = self.config.get_int("Speed", 0)
        if not 0 <= initial <= self._speeds:
            raise InvalidValueError(
                f"[{self.config.section_name}] Speed: "
                f"expected 0..{self._speeds}, got {initial}"
            )

        self._all = set(range(1, self._speeds + 1))
        self._windings: dict[int, bool] = {n: n == initial for n in self._all}
        #: winding of the most recent ON telegram; None = no switch to compare with
        self._last_on: int | None = initial if initial else None
        #: windings that received OFF since the last ON telegram
        self._offs: set[int] = set()

        self._statuses: dict[int, StatusPoint] = {}
        for n in sorted(self._all):
            self.add(
                ActionPoint(
                    f"a_speed{n}", self.config.get_ga(f"ActionSpeed{n}"),
                    DPT_BOOL, partial(self.on_relay, n),
                )
            )
            if f"StatusSpeed{n}" in self.config:
                self._statuses[n] = self.add(
                    StatusPoint(
                        f"speed{n}", self.config.get_ga(f"StatusSpeed{n}"),
                        DPT_BOOL, partial(self._windings.get, n),
                    )
                )

    # --- bus -----------------------------------------------------------------
    def on_relay(self, winding: int, value: bool) -> None:
        if value:
            self._check_switch_algorithm(winding)
            self._windings[winding] = True
            self._last_on = winding
            self._offs.clear()
        else:
            self._windings[winding] = False
            self._offs.add(winding)
        point = self._statuses.get(winding)
        if point is not None:
            self.publish(point)

    def _check_switch_algorithm(self, winding: int) -> None:
        """Break-before-make: before an ON every winding must be off and have been sent an OFF."""
        still_on = sorted(m for m, on in self._windings.items() if on and m != winding)
        if still_on:
            self.log.error(
                "switching algorithm violated: ON for winding %d while winding(s) %s "
                "are still energized — the actuator must switch all windings off first",
                winding, still_on,
            )
        if self._last_on is not None and self._last_on != winding:
            missing = sorted(self._all - self._offs)
            if missing:
                self.log.error(
                    "switching algorithm violated: switch from winding %d to %d "
                    "without OFF for winding(s) %s — the actuator must switch off "
                    "all windings before the new ON",
                    self._last_on, winding, missing,
                )

    # --- local commands ------------------------------------------------------
    @local_command("set_speed", description="Speed step 0..Speeds (0 = off)", args_schema={"speed": int})
    def cmd_set_speed(self, speed: int) -> dict:
        if not 0 <= speed <= self._speeds:
            raise CommandArgumentError(
                f"Command 'set_speed': speed must be 0..{self._speeds}"
            )
        self._force_speed(speed)
        return {"speed": speed}

    @local_command("off", description="Switch the fan off (all windings)")
    def cmd_off(self) -> dict:
        self._force_speed(0)
        return {"speed": 0}

    # --- logic ---------------------------------------------------------------
    def _force_speed(self, speed: int) -> None:
        """Local (panel) override: set the windings directly, reset tracking."""
        for n in self._all:
            self._windings[n] = n == speed
        self._last_on = speed if speed else None
        self._offs.clear()
        for point in self._statuses.values():
            self.publish(point)
