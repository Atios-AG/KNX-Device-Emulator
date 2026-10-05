"""Virtual outlet / relay (DPT 1.001).

An example of a minimal device. It demonstrates all three actuation channels:
  * from the bus — on_action() when a Write arrives at the Action address;
  * polling      — read_status() when a Read arrives at the Status address;
  * locally      — @local_command (like a button press on a panel).

Config:
    [outlet0]
    type     = outlet
    Action   = 1/1/1
    Status   = 2/2/2
    Inverted = True      ; the physical state is inverted relative to the bus
"""

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL


class OutletDevice(BaseDevice):
    TYPE = "outlet"

    def setup(self) -> None:
        self.inverted = self.config.get_bool("Inverted", default=False)
        self._state = False  # the physical state of the relay (on/off)

        self.action = self.add(
            ActionPoint("action", self.config.get_ga("Action"), DPT_BOOL, self.on_action)
        )
        self.status = self.add(
            StatusPoint("on", self.config.get_ga("Status"), DPT_BOOL, self.read_status)
        )

    # --- bus -----------------------------------------------------------------
    def on_action(self, bus_value: bool) -> None:
        # the value on the bus is inverted into the physical state and vice versa
        self._set(self._invert(bus_value))

    def read_status(self) -> bool:
        return self._invert(self._state)

    # --- local commands (panel) ----------------------------------------------
    @local_command("toggle", description="Toggle the outlet state")
    def cmd_toggle(self) -> dict:
        self._set(not self._state)
        return self.state_snapshot()

    @local_command("set", description="Set the state", args_schema={"on": bool})
    def cmd_set(self, on: bool) -> dict:
        self._set(on)
        return self.state_snapshot()

    # --- shared logic --------------------------------------------------------
    def _invert(self, value: bool) -> bool:
        return (not value) if self.inverted else value

    def _set(self, physical: bool) -> None:
        self._state = bool(physical)
        self.publish(self.status)  # report the new status to the bus, like hardware
