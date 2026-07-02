"""Виртуальный диммер: вкл/выкл (DPT 1.001) + уровень яркости (DPT 5.001).

Показывает устройство с несколькими точками данных.

Конфиг:
    [dimmer_kitchen]
    type      = dimmer
    Action    = 1/2/1     ; вкл/выкл
    ActionDim = 1/2/2     ; установить уровень 0..100 %
    Status    = 2/2/1     ; статус вкл/выкл
    StatusDim = 2/2/2     ; статус уровня
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

    # --- шина ---------------------------------------------------------------
    def on_switch(self, value: bool) -> None:
        self._apply(on=value)

    def on_dim(self, level: float) -> None:
        self._apply(level=level)

    # --- локальные команды --------------------------------------------------
    @local_command("toggle", description="Переключить вкл/выкл")
    def cmd_toggle(self) -> dict:
        return self._apply(on=not self._on)

    @local_command("set_level", description="Задать яркость", args_schema={"level": float})
    def cmd_set_level(self, level: float) -> dict:
        return self._apply(level=level)

    # --- логика -------------------------------------------------------------
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
