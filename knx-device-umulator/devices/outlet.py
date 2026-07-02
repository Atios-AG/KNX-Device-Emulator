"""Виртуальная розетка / реле (DPT 1.001).

Пример минимального устройства. Демонстрирует все три канала воздействия:
  * с шины  — on_action() на приход Write по Action-адресу;
  * опрос   — read_status() на приход Read по Status-адресу;
  * локально — @local_command (как нажатие кнопки на панели).

Конфиг:
    [outlet0]
    type     = outlet
    Action   = 1/1/1
    Status   = 2/2/2
    Inverted = True      ; физическое состояние инвертировано относительно шины
"""

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL


class OutletDevice(BaseDevice):
    TYPE = "outlet"

    def setup(self) -> None:
        self.inverted = self.config.get_bool("Inverted", default=False)
        self._state = False  # физическое состояние реле (вкл/выкл)

        self.action = self.add(
            ActionPoint("action", self.config.get_ga("Action"), DPT_BOOL, self.on_action)
        )
        self.status = self.add(
            StatusPoint("on", self.config.get_ga("Status"), DPT_BOOL, self.read_status)
        )

    # --- шина ---------------------------------------------------------------
    def on_action(self, bus_value: bool) -> None:
        # значение на шине инвертируется в физическое состояние и наоборот
        self._set(self._invert(bus_value))

    def read_status(self) -> bool:
        return self._invert(self._state)

    # --- локальные команды (панель) -----------------------------------------
    @local_command("toggle", description="Переключить состояние розетки")
    def cmd_toggle(self) -> dict:
        self._set(not self._state)
        return self.state_snapshot()

    @local_command("set", description="Задать состояние", args_schema={"on": bool})
    def cmd_set(self, on: bool) -> dict:
        self._set(on)
        return self.state_snapshot()

    # --- общая логика -------------------------------------------------------
    def _invert(self, value: bool) -> bool:
        return (not value) if self.inverted else value

    def _set(self, physical: bool) -> None:
        self._state = bool(physical)
        self.publish(self.status)  # сообщить новый статус на шину, как железо
