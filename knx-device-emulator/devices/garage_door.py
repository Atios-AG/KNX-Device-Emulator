"""Virtual garage door drive: one-bit command, three optional status flavours.

The only control object is a bit (DPT 1.008 Up/Down): 0 = open (up),
1 = close (down); `Inverted = True` swaps the two. Like a real motor, the
drive needs `TravelSec` seconds to travel between the end positions. An
opposite command while the door is moving reverses it from the current
virtual position — the rest of the travel takes a proportional time. A
command that asks for the position the door is already in (or is already
moving to) is ignored: no telegram, only a line in the log.

Status flavours — all optional and independent. A flavour is active when its
group address is set; any combination works, even all three at once:

  * `Status`         — one bit (DPT 1.008) that follows the command
                       semantics: with `Inverted = False` 1 = closed,
                       0 = open. Updated only at the end positions.
  * `StatusPosition` — 0..100 % (DPT 5.001), 0 % = closed, 100 % = open
                       (`InvertedPosition = True`: 0 % = open, 100 % = closed).
                       Updated only at the end positions.
  * `SensorOpened` /
    `SensorClosed`   — two end-position sensors (DPT 1.002), 1 = the door
                       rests at that end (`InvertedSensorOpened` /
                       `InvertedSensorClosed = True`: 0 = at that end, i.e. a
                       normally-closed contact). Leaving an end drops its
                       sensor to 0 right away, reaching the other end raises
                       that sensor to 1 — the sequence of a real pair of limit
                       switches (opening from the closed position):

        moment              SensorOpened    SensorClosed
        closed                   0               1
        started opening          0               0   (telegram Closed -> 0)
        travelling               0               0
        fully open               1               0   (telegram Opened -> 1)

Local commands: `open` and `close` (like the bus command) and `stop`, which
halts the drive half-way: both sensors stay 0, the bit and the percentage
keep reporting the last end position reached.

Impulse mode (`Impulse = True`): a drive with a stop state, where every bus
telegram is one press of the button. A telegram while the door is moving
halts it (like `stop`), a telegram while it stands moves it as the bit asks
(same as the default mode). This is the model the bridge itself assumes for
`GarageHasStopState`: re-target = halt + second pulse one second later.

Config:
    [garage0]
    type           = garage_door
    Action         = 1/7/1     ; open/close command (DPT 1.008)
    Status         = 2/7/1     ; optional — one-bit status (DPT 1.008)
    StatusPosition = 2/7/2     ; optional — 0..100 % position (DPT 5.001)
    SensorOpened   = 2/7/3     ; optional — "open" end sensor (DPT 1.002)
    SensorClosed   = 2/7/4     ; optional — "closed" end sensor (DPT 1.002)
    TravelSec      = 15        ; full travel time, seconds (10 by default)
    State          = closed    ; initial state: closed | open
    Inverted       = False     ; True: command 1 = open, status 1 = open
    InvertedPosition     = False  ; True: 0 % = open, 100 % = closed
    InvertedSensorOpened = False  ; True: SensorOpened 0 = door rests fully open
    InvertedSensorClosed = False  ; True: SensorClosed 0 = door rests fully closed
    Impulse        = False     ; True: a telegram while moving halts the drive
"""

from __future__ import annotations

import asyncio
import time

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL, DPT_SCALING
from core.exceptions import InvalidValueError

CLOSED = "closed"
OPEN = "open"
OPENING = "opening"
CLOSING = "closing"
STOPPED = "stopped"  # halted half-way by the `stop` command


class GarageDoorDevice(BaseDevice):
    TYPE = "garage_door"

    DEFAULT_TRAVEL_SEC = 10.0

    def setup(self) -> None:
        self.inverted = self.config.get_bool("Inverted", default=False)
        self.inverted_position = self.config.get_bool("InvertedPosition", default=False)
        self.inverted_sensor_opened = self.config.get_bool("InvertedSensorOpened", default=False)
        self.inverted_sensor_closed = self.config.get_bool("InvertedSensorClosed", default=False)
        self.impulse = self.config.get_bool("Impulse", default=False)
        self._travel = self.config.get_float("TravelSec", self.DEFAULT_TRAVEL_SEC)
        if self._travel <= 0:
            raise InvalidValueError(
                f"[{self.config.section_name}] TravelSec: "
                f"expected a positive number of seconds, got {self._travel}"
            )
        initial = str(self.config.get("State", CLOSED)).strip().lower()
        if initial not in (CLOSED, OPEN):
            raise InvalidValueError(
                f"[{self.config.section_name}] State: "
                f"expected 'closed' or 'open', got '{initial}'"
            )

        # --- the physics of the drive ---------------------------------------
        #: the door position, 0.0 = closed .. 1.0 = open (valid while idle)
        self._position = 1.0 if initial == OPEN else 0.0
        #: +1 = opening, -1 = closing, 0 = idle
        self._direction = 0
        #: where and when the current travel started (valid while moving)
        self._move_from = self._position
        self._move_started = 0.0
        #: when the current travel is due to finish (valid while moving)
        self._arrival_due = 0.0
        #: the last end position reached — what the bit and the % report
        self._last_end = initial
        self._timer: asyncio.TimerHandle | None = None
        #: monotonic clock; tests replace it with a fake one
        self._clock = time.monotonic

        # --- group objects --------------------------------------------------
        self.action = self.add(
            ActionPoint("action", self.config.get_ga("Action"), DPT_BOOL, self.on_action)
        )
        self.status: StatusPoint | None = None
        self.status_position: StatusPoint | None = None
        self.sensor_opened: StatusPoint | None = None
        self.sensor_closed: StatusPoint | None = None
        if "Status" in self.config:
            self.status = self.add(
                StatusPoint("status", self.config.get_ga("Status"), DPT_BOOL, self.read_status)
            )
        if "StatusPosition" in self.config:
            self.status_position = self.add(
                StatusPoint(
                    "status_position", self.config.get_ga("StatusPosition"),
                    DPT_SCALING, self.read_position,
                )
            )
        if "SensorOpened" in self.config:
            self.sensor_opened = self.add(
                StatusPoint(
                    "sensor_opened", self.config.get_ga("SensorOpened"),
                    DPT_BOOL, self.read_sensor_opened,
                )
            )
        if "SensorClosed" in self.config:
            self.sensor_closed = self.add(
                StatusPoint(
                    "sensor_closed", self.config.get_ga("SensorClosed"),
                    DPT_BOOL, self.read_sensor_closed,
                )
            )

    # --- bus -----------------------------------------------------------------
    def on_action(self, bus_value: bool) -> None:
        # DPT 1.008: 0 = up (open), 1 = down (close); Inverted swaps them
        if self.impulse and self._direction != 0:
            self.log.info(
                "impulse (value %d) while %s: halting the drive", int(bus_value), self.state
            )
            self._stop()
            return
        self._command(CLOSING if self._invert(bus_value) else OPENING)

    def read_status(self) -> bool:
        """One-bit status: follows the command semantics (1 = closed by default)."""
        return self._invert(self._last_end == CLOSED)

    def read_position(self) -> float:
        """0..100 %: only the end positions are reported (InvertedPosition flips the scale)."""
        pct = 100.0 if self._last_end == OPEN else 0.0
        return 100.0 - pct if self.inverted_position else pct

    def read_sensor_opened(self) -> bool:
        at_end = self._direction == 0 and self._position >= 1.0
        return (not at_end) if self.inverted_sensor_opened else at_end

    def read_sensor_closed(self) -> bool:
        at_end = self._direction == 0 and self._position <= 0.0
        return (not at_end) if self.inverted_sensor_closed else at_end

    # --- local commands (panel) ----------------------------------------------
    @local_command("open", description="Open the door (like the bus command)")
    def cmd_open(self) -> dict:
        self._command(OPENING)
        return self.state_snapshot()

    @local_command("close", description="Close the door (like the bus command)")
    def cmd_close(self) -> dict:
        self._command(CLOSING)
        return self.state_snapshot()

    @local_command("stop", description="Halt the drive half-way")
    def cmd_stop(self) -> dict:
        self._stop()
        return self.state_snapshot()

    # --- life-cycle ----------------------------------------------------------
    async def stop(self) -> None:
        self._cancel_timer()

    # --- state ---------------------------------------------------------------
    def state_snapshot(self) -> dict:
        snapshot = {
            "state": self.state,
            "position": round(self.current_position() * 100, 1),
        }
        snapshot.update(super().state_snapshot())
        return snapshot

    @property
    def state(self) -> str:
        if self._direction > 0:
            return OPENING
        if self._direction < 0:
            return CLOSING
        if self._position >= 1.0:
            return OPEN
        if self._position <= 0.0:
            return CLOSED
        return STOPPED

    def current_position(self) -> float:
        """The virtual position right now, 0.0 = closed .. 1.0 = open."""
        if self._direction == 0:
            return self._position
        elapsed = self._clock() - self._move_started
        pos = self._move_from + self._direction * elapsed / self._travel
        return min(1.0, max(0.0, pos))

    # --- logic ---------------------------------------------------------------
    def _invert(self, value: bool) -> bool:
        return (not value) if self.inverted else value

    def _command(self, motion: str) -> None:
        direction = 1 if motion == OPENING else -1
        target = OPEN if direction > 0 else CLOSED
        pos = self.current_position()

        if self._direction == direction:
            self.log.info("command '%s' ignored: the door is already %s", target, motion)
            return
        if self._direction == 0 and pos == (1.0 if direction > 0 else 0.0):
            self.log.info("command '%s' ignored: the door is already %s", target, target)
            return

        leaving_end = self._direction == 0 and pos in (0.0, 1.0)
        if self._direction != 0:
            self._cancel_timer()
            self.log.info(
                "reversing at %.0f %%: %s -> %s", pos * 100, self.state, motion
            )

        remaining = (1.0 - pos if direction > 0 else pos) * self._travel
        now = self._clock()
        self._move_from = pos
        self._move_started = now
        self._arrival_due = now + remaining
        self._direction = direction
        self.log.info(
            "%s from %.0f %% — fully %s in %.1f s", motion, pos * 100, target, remaining
        )
        self._schedule_arrival(remaining)

        if leaving_end:
            # the limit switch of the end we have just left drops to 0
            sensor = self.sensor_closed if pos == 0.0 else self.sensor_opened
            if sensor is not None:
                self.publish(sensor)

    def _arrive(self) -> None:
        """The travel is over: the door rests at the target end position."""
        self._timer = None
        if self._direction == 0:
            return
        reached = OPEN if self._direction > 0 else CLOSED
        self._position = 1.0 if reached == OPEN else 0.0
        self._direction = 0
        self._last_end = reached
        self.log.info("fully %s", reached)
        if self.status is not None:
            self.publish(self.status)
        if self.status_position is not None:
            self.publish(self.status_position)
        sensor = self.sensor_opened if reached == OPEN else self.sensor_closed
        if sensor is not None:
            self.publish(sensor)

    def _stop(self) -> None:
        if self._direction == 0:
            self.log.info("command 'stop' ignored: the door is not moving (%s)", self.state)
            return
        pos = self.current_position()
        if pos in (0.0, 1.0):
            self._arrive()  # the timer was about to fire anyway
            return
        self._cancel_timer()
        self._position = pos
        self._direction = 0
        # nothing goes to the bus: the sensors are already 0, the bit and the
        # percentage report end positions only
        self.log.info("stopped at %.0f %%", pos * 100)

    # --- timer ---------------------------------------------------------------
    def _schedule_arrival(self, delay: float) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # no event loop (unit tests): the arrival is triggered by hand
            self.log.debug("no running event loop — arrival timer not scheduled")
            return
        self._timer = loop.call_later(delay, self._arrive)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
