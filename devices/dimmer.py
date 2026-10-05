"""Virtual dimmer: on/off (DPT 1.001) + brightness level (DPT 5.001).

Shows a device with several data points.

Config:
    [dimmer_kitchen]
    type      = dimmer
    Action    = 1/2/1     ; on/off
    ActionDim = 1/2/2     ; set the level 0..100 %
    Status    = 2/2/1     ; on/off status
    StatusDim = 2/2/2     ; level status
"""

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL, DPT_SCALING


class DimmerDevice(BaseDevice):
    TYPE = "dimmer"

    def setup(self) -> None:
        self._on = False
        self._level = 0.0

        self.action = self.add(
            ActionPoint("action", self.config.get_ga("Action"), DPT_BOOL, self.on_switch)
        )
        self.action_dim = self.add(
            ActionPoint(
                "action_dim", self.config.get_ga("ActionDim"), DPT_SCALING, self.on_dim
            )
        )
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
        self.publish(self.status)
        self.publish(self.status_dim)
        return self.state_snapshot()
