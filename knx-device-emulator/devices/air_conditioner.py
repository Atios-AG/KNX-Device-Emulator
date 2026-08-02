"""Virtual air conditioner (Room Air Conditioner).

Fully repeats the thermostat (target/current temperature, target/current mode,
On/Off, summer/winter mode) and adds one element — the **fan**, controlled by
percentages 0..100 (DPT 5.001), a Control + Status channel.

Implemented as a subclass of ThermostatDevice: all the climate logic and its
local commands (set_onoff/set_mode/set_setpoint/set_current/set_season) are
inherited automatically, only the fan is added here. One file — one device, the
core of the project stays untouched.

Config — all the thermostat keys plus:
    ActionFan = 1/4/5        ; set the speed 0..100 %
    StatusFan = 2/4/5        ; speed status
    Fan       = 0            ; initial speed (optional)
"""

from core.datapoint import ActionPoint, StatusPoint
from core.device import local_command
from core.dpt import DPT_SCALING

from devices.thermostat import ThermostatDevice


class AirConditionerDevice(ThermostatDevice):
    TYPE = "air_conditioner"

    def setup(self) -> None:
        super().setup()  # the whole climate part of the thermostat

        self._fan = max(0.0, min(100.0, float(self.config.get("Fan", 0.0))))
        self.action_fan = self.add(
            ActionPoint("a_fan", self.config.get_ga("ActionFan"), DPT_SCALING, self.on_fan)
        )
        self.status_fan = self.add(
            StatusPoint("fan", self.config.get_ga("StatusFan"), DPT_SCALING, lambda: round(self._fan, 1))
        )

    # --- fan -----------------------------------------------------------------
    def on_fan(self, value: float) -> None:  # command from the bus
        self._set_fan(value)

    @local_command("set_fan", description="Fan speed 0..100 %", args_schema={"level": float})
    def cmd_set_fan(self, level: float) -> dict:  # command from the panel
        self._set_fan(level)
        return self.state_snapshot()

    def _set_fan(self, level: float) -> None:
        self._fan = max(0.0, min(100.0, float(level)))
        self.publish(self.status_fan)
