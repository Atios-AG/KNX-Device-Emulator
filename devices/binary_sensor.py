"""Virtual binary sensor (DPT 1.xxx): motion, contact, leak, rain, ...

A status-only device: nothing on the bus can change it, so it has no Action
address. A local command sets what the sensor "sees"; the device then
broadcasts the new state to its Status address the way a real sensor reports
an event, and answers a Read on that address with the current state.

Config:
    [motion_hall]
    type     = binary_sensor
    Status   = 3/0/1
    Inverted = False     ; True: the bus carries 0 for detected, 1 for idle
"""

from core.datapoint import StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL


class BinarySensorDevice(BaseDevice):
    TYPE = "binary_sensor"

    def setup(self) -> None:
        self.inverted = self.config.get_bool("Inverted", default=False)
        self._detected = False

        self.status = self.add(
            StatusPoint("on", self.config.get_ga("Status"), DPT_BOOL, self.read_status)
        )

    # --- bus -----------------------------------------------------------------
    def read_status(self) -> bool:
        return self._detected != self.inverted

    # --- local commands ------------------------------------------------------
    @local_command("set", description="Set the detected state", args_schema={"on": bool})
    def cmd_set(self, on: bool) -> dict:
        self._detected = bool(on)
        self.publish(self.status)
        return self.state_snapshot()

    @local_command("toggle", description="Toggle the detected state")
    def cmd_toggle(self) -> dict:
        return self.cmd_set(not self._detected)
