"""Virtual roller shutter / blind drive (KNX conventions: 0 % = open, 100 % = closed).

Command objects:
  * `Movement`       — DPT 1.008 Up/Down: 0 = up (open), 1 = down (close).
  * `Stop`           — DPT 1.010 Stop: any value halts the drive.
  * `TargetPosition` — DPT 5.001: absolute target, 0 % = open .. 100 % = closed.

Status objects (all optional, active when the group address is set):
  * `CurrentPosition` — DPT 5.001, reported when the drive comes to rest (end
                        position, absolute target reached or stopped half-way).
  * `StatusMovement`  — DPT 1.008 bit reported together with the position:
                        1 while the shutter rests fully closed, else 0.

Like a real motor the drive needs `TravelSec` for a full run; a target in the
opposite direction reverses the drive from its virtual position. A command for
the position the shutter is already at (or is already moving to) is ignored with
a log line. Local commands: `up`, `down`, `stop`, `position` (percent=NN).

Config:
    [shutter0]
    type            = shutter
    Movement        = 3/1/1     ; up/down command (DPT 1.008)
    Stop            = 3/1/3     ; optional — stop command (DPT 1.010)
    TargetPosition  = 3/1/4     ; optional — absolute target (DPT 5.001)
    CurrentPosition = 3/1/5     ; optional — position status (DPT 5.001)
    StatusMovement  = 3/1/2     ; optional — closed bit status (DPT 1.008)
    TravelSec       = 10        ; full travel time, seconds (10 by default)
    Position        = 0         ; initial position in percent (0 = open)
"""

from __future__ import annotations

import asyncio

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL, DPT_SCALING
from core.exceptions import InvalidValueError

import time


class ShutterDevice(BaseDevice):
    TYPE = "shutter"

    DEFAULT_TRAVEL_SEC = 10.0

    def setup(self) -> None:
        self._travel = self.config.get_float("TravelSec", self.DEFAULT_TRAVEL_SEC)
        if self._travel <= 0:
            raise InvalidValueError(
                f"[{self.config.section_name}] TravelSec: "
                f"expected a positive number of seconds, got {self._travel}"
            )
        initial = self.config.get_float("Position", 0.0)
        if not 0.0 <= initial <= 100.0:
            raise InvalidValueError(
                f"[{self.config.section_name}] Position: expected 0..100, got {initial}"
            )

        #: position in percent, 0 = open .. 100 = closed (valid while idle)
        self._position = float(initial)
        #: +1 = closing (down), -1 = opening (up), 0 = idle
        self._direction = 0
        #: target of the current travel in percent (valid while moving)
        self._target = self._position
        self._move_from = self._position
        self._move_started = 0.0
        self._timer: asyncio.TimerHandle | None = None
        self._clock = time.monotonic

        self.movement = self.add(
            ActionPoint("movement", self.config.get_ga("Movement"), DPT_BOOL, self.on_movement)
        )
        self.stop_point: ActionPoint | None = None
        self.target_position: ActionPoint | None = None
        self.status_position: StatusPoint | None = None
        self.status_movement: StatusPoint | None = None
        if "Stop" in self.config:
            self.stop_point = self.add(
                ActionPoint("stop", self.config.get_ga("Stop"), DPT_BOOL, self.on_stop)
            )
        if "TargetPosition" in self.config:
            self.target_position = self.add(
                ActionPoint(
                    "target_position", self.config.get_ga("TargetPosition"),
                    DPT_SCALING, self.on_target_position,
                )
            )
        if "CurrentPosition" in self.config:
            self.status_position = self.add(
                StatusPoint(
                    "current_position", self.config.get_ga("CurrentPosition"),
                    DPT_SCALING, self.read_position,
                )
            )
        if "StatusMovement" in self.config:
            self.status_movement = self.add(
                StatusPoint(
                    "status_movement", self.config.get_ga("StatusMovement"),
                    DPT_BOOL, self.read_movement,
                )
            )

    # --- bus -----------------------------------------------------------------
    def on_movement(self, bus_value: bool) -> None:
        # DPT 1.008: 0 = up (open, 0 %), 1 = down (close, 100 %)
        self._go_to(100.0 if bus_value else 0.0)

    def on_stop(self, bus_value: bool) -> None:
        self._stop()

    def on_target_position(self, bus_value: float) -> None:
        self._go_to(float(bus_value))

    def read_position(self) -> float:
        """Reported only at rest: the position where the drive stopped."""
        return round(self._position, 1)

    def read_movement(self) -> bool:
        """1 while the shutter rests fully closed."""
        return self._direction == 0 and self._position >= 100.0

    # --- local commands (panel) ----------------------------------------------
    @local_command("up", description="Open the shutter fully (like Movement = 0)")
    def cmd_up(self) -> dict:
        self._go_to(0.0)
        return self.state_snapshot()

    @local_command("down", description="Close the shutter fully (like Movement = 1)")
    def cmd_down(self) -> dict:
        self._go_to(100.0)
        return self.state_snapshot()

    @local_command("stop", description="Halt the drive")
    def cmd_stop(self) -> dict:
        self._stop()
        return self.state_snapshot()

    @local_command("position", description="Move to a position in percent (0 = open)",
                   args_schema={"percent": float})
    def cmd_position(self, percent: float) -> dict:
        self._go_to(float(percent))
        return self.state_snapshot()

    # --- life-cycle ----------------------------------------------------------
    async def stop(self) -> None:
        self._cancel_timer()

    # --- state ---------------------------------------------------------------
    def state_snapshot(self) -> dict:
        snapshot = {"state": self.state, "position": round(self.current_position(), 1)}
        snapshot.update(super().state_snapshot())
        return snapshot

    @property
    def state(self) -> str:
        if self._direction > 0:
            return "closing"
        if self._direction < 0:
            return "opening"
        return "idle"

    def current_position(self) -> float:
        """The virtual position right now, percent, 0 = open .. 100 = closed."""
        if self._direction == 0:
            return self._position
        elapsed = self._clock() - self._move_started
        pos = self._move_from + self._direction * 100.0 * elapsed / self._travel
        return min(100.0, max(0.0, pos))

    # --- logic ---------------------------------------------------------------
    def _go_to(self, target: float) -> None:
        target = min(100.0, max(0.0, target))
        pos = self.current_position()
        if self._direction != 0 and target == self._target:
            self.log.info("target %.0f %% ignored: already moving there", target)
            return
        if self._direction == 0 and pos == target:
            self.log.info("target %.0f %% ignored: already there", target)
            return
        if self._direction != 0:
            self._cancel_timer()
            self.log.info("reversing/retargeting at %.0f %% -> %.0f %%", pos, target)
        self._direction = 1 if target > pos else -1
        self._target = target
        self._move_from = pos
        self._move_started = self._clock()
        remaining = abs(target - pos) / 100.0 * self._travel
        self.log.info(
            "%s from %.0f %% to %.0f %% — there in %.1f s",
            "closing" if self._direction > 0 else "opening", pos, target, remaining,
        )
        self._schedule_arrival(remaining)

    def _arrive(self) -> None:
        self._timer = None
        if self._direction == 0:
            return
        self._position = self._target
        self._direction = 0
        self.log.info("stopped at %.0f %% (target reached)", self._position)
        self._publish_rest()

    def _stop(self) -> None:
        if self._direction == 0:
            self.log.info("command 'stop' ignored: the drive is not moving")
            return
        self._position = self.current_position()
        self._cancel_timer()
        self._direction = 0
        self.log.info("stopped at %.0f %% (stop command)", self._position)
        self._publish_rest()

    def _publish_rest(self) -> None:
        if self.status_position is not None:
            self.publish(self.status_position)
        if self.status_movement is not None:
            self.publish(self.status_movement)

    # --- timer ---------------------------------------------------------------
    def _schedule_arrival(self, delay: float) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.log.debug("no running event loop — arrival timer not scheduled")
            return
        self._timer = loop.call_later(delay, self._arrive)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
