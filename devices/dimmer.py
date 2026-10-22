"""Virtual dimmer: on/off (DPT 1.001) + brightness level (DPT 5.001).

Shows a device with several data points.

Config:
    [dimmer_kitchen]
    type      = dimmer
    Action    = 1/2/1     ; optional, on/off
    ActionDim = 1/2/2     ; set the level 0..100 %
    Status    = 2/2/1     ; optional, on/off status
    StatusDim = 2/2/2     ; level status
    Level     = 0         ; initial level 0..100 %, on when above 0 (0 by default)
"""

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL, DPT_SCALING


class DimmerDevice(BaseDevice):
    TYPE = "dimmer"

    def setup(self) -> None:
        self._level = max(0.0, min(100.0, self.config.get_float("Level", 0.0)))
        self._on = self._level > 0

        self.action: ActionPoint | None = None
        if "Action" in self.config:
            self.action = self.add(
                ActionPoint("action", self.config.get_ga("Action"), DPT_BOOL, self.on_switch)
            )
        self.action_dim = self.add(
            ActionPoint(
                "action_dim", self.config.get_ga("ActionDim"), DPT_SCALING, self.on_dim
            )
        )
        self.status: StatusPoint | None = None
        if "Status" in self.config:
            self.status = self.add(
                StatusPoint("on", self.config.get_ga("Status"), DPT_BOOL, lambda: self._on)
            )
        self.status_dim = self.add(
            StatusPoint(
                "level", self.config.get_ga("StatusDim"), DPT_SCALING, lambda: self._level
            )
        )

    # --- bus -----------------------------------------------------------------
    def on_switch(self, value: bool) -> None:
        self._apply(on=value)

    def on_dim(self, level: float) -> None:
        self._apply(level=level)

    # --- local commands ------------------------------------------------------
    @local_command("toggle", description="Toggle on/off")
    def cmd_toggle(self) -> dict:
        return self._apply(on=not self._on)

    @local_command("set", description="Set on/off (on restores the last level, or 100 %)",
                   args_schema={"on": bool})
    def cmd_set(self, on: bool) -> dict:
        return self._apply(on=on)

    @local_command("set_level", description="Set the brightness", args_schema={"level": float})
    def cmd_set_level(self, level: float) -> dict:
        return self._apply(level=level)

    # --- logic ---------------------------------------------------------------
    def _apply(self, on: bool | None = None, level: float | None = None) -> dict:
        if level is not None:
            self._level = max(0.0, min(100.0, float(level)))
            self._on = self._level > 0
        if on is not None:
            self._on = bool(on)
            if self._on and self._level == 0:
                self._level = 100.0
            if not self._on:
                self._level = 0.0
        if self.status is not None:
            self.publish(self.status)
        self.publish(self.status_dim)
        return self.state_snapshot()

    def state_snapshot(self) -> dict:
        # on/off is part of the state also without a Status object
        return {"on": self._on, "level": self._level}
