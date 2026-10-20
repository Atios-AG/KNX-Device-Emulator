"""Virtual analog sensor (DPT 9.xxx, 2-byte float): temperature, humidity,
illuminance, ...

Status-only like the binary sensor: a local command sets the measured value,
the device broadcasts it to its Status address and answers Reads there. Every
9.xxx sub-type shares the same wire format, so one plugin serves them all — the
consumer decides what the number means.

Config:
    [temp_hall]
    type   = analog_sensor
    Status = 4/0/1
    Value  = 21.5        ; initial value (default 0)
"""

from core.datapoint import StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_TEMPERATURE


class AnalogSensorDevice(BaseDevice):
    TYPE = "analog_sensor"

    def setup(self) -> None:
        self._value = self.config.get_float("Value", default=0.0)

        self.status = self.add(
            StatusPoint("value", self.config.get_ga("Status"), DPT_TEMPERATURE, lambda: self._value)
        )

    # --- local commands ------------------------------------------------------
    @local_command("set", description="Set the measured value", args_schema={"value": float})
    def cmd_set(self, value: float) -> dict:
        self._value = float(value)
        self.publish(self.status)
        return self.state_snapshot()
