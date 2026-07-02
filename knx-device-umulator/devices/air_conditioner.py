"""Виртуальный кондиционер (Room Air Conditioner).

Полностью повторяет термостат (целевая/текущая температура, целевой/текущий
режим, On/Off, летний/зимний режим) и добавляет один элемент — **вентилятор**,
управляемый процентами 0..100 (DPT 5.001), канал Control + Status.

Реализован как наследник ThermostatDevice: вся климатическая логика и её
локальные команды (set_onoff/set_mode/set_setpoint/set_current/set_season)
наследуются автоматически, здесь добавляется только вентилятор. Один файл —
одно устройство, ядро проекта не меняется.

Конфиг — все ключи термостата плюс:
    ActionFan = 1/4/5        ; задать скорость 0..100 %
    StatusFan = 2/4/5        ; статус скорости
    Fan       = 0            ; начальная скорость (опционально)
"""

from core.datapoint import ActionPoint, StatusPoint
from core.device import local_command
from core.dpt import DPT_SCALING

from devices.thermostat import ThermostatDevice


class AirConditionerDevice(ThermostatDevice):
    TYPE = "air_conditioner"

    def setup(self) -> None:
        super().setup()  # вся климатическая часть термостата

        self._fan = max(0.0, min(100.0, float(self.config.get("Fan", 0.0))))
        self.action_fan = self.add(
            ActionPoint("a_fan", self.config.get_ga("ActionFan"), DPT_SCALING, self.on_fan)
        )
        self.status_fan = self.add(
            StatusPoint("fan", self.config.get_ga("StatusFan"), DPT_SCALING, lambda: round(self._fan, 1))
        )

    # --- вентилятор ---------------------------------------------------------
    def on_fan(self, value: float) -> None:  # команда с шины
        self._set_fan(value)

    @local_command("set_fan", description="Скорость вентилятора 0..100 %", args_schema={"level": float})
    def cmd_set_fan(self, level: float) -> dict:  # команда с панели
        self._set_fan(level)
        return self.state_snapshot()

    def _set_fan(self, level: float) -> None:
        self._fan = max(0.0, min(100.0, float(level)))
        self.publish(self.status_fan)
