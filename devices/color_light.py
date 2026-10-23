"""Virtual KNX light: on/off, brightness, color temperature and color.

Built from the objects of a KNX LED controller (MDT AKD-0x24x.02, technical
manual 5.3.2 and 5.3.8): on/off, brightness, the color temperature in Kelvin
(DPT 7.600, object 75) or as the cold white share in % (object 74: 0 % is
WarmKelvin, 100 % ColdKelvin, linear in Kelvin), and the color as H, S, V in
one 3-byte object (DPT 232.600, objects 67 and 82: hue 0..255 for 0..360°,
saturation and value 0..255 for 0..100 %). Every object is optional, active
when its group address is set.

Switching on brings back the last brightness (100 % the first time). A
brightness or an HSV value above 0 switches on and 0 switches off; the color
temperature and the color alone never switch. A Kelvin from the bus outside
WarmKelvin..ColdKelvin is clamped. The brightness status is 0 % and the HSV
status has V = 0 while off. A status is sent when its value changes and in
reply to its own command. Local commands: `toggle`, `set` (on=), `set_level`
(level=), `set_kelvin` (kelvin=), `set_hsv` (hue=, saturation=, level=).

Config:
    [lamp_living]
    type            = color_light
    Action          = 1/5/1     ; optional, on/off (DPT 1.001)
    Status          = 1/5/2     ; optional, on/off status
    ActionDim       = 1/5/3     ; optional, brightness 0..100 % (DPT 5.001)
    StatusDim       = 1/5/4     ; optional, brightness status
    ActionKelvin    = 1/5/5     ; optional, color temperature in K (DPT 7.600)
    StatusKelvin    = 1/5/6     ; optional
    ActionColorTemp = 1/5/7     ; optional, cold white share 0..100 % (DPT 5.001)
    StatusColorTemp = 1/5/8     ; optional
    ActionHSV       = 1/5/9     ; optional, H, S, V in 3 bytes (DPT 232.600)
    StatusHSV       = 1/5/10    ; optional
    WarmKelvin      = 2700      ; the warm end, K
    ColdKelvin      = 6500      ; the cold end, K
    Level           = 0         ; initial brightness 0..100 %, on when above 0
    Kelvin          = 2700      ; initial color temperature, K (WarmKelvin by default)
    Hue             = 0         ; initial hue 0..360°
    Saturation      = 0         ; initial saturation 0..100 %
"""

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL, DPT_COLOR_3BYTE, DPT_COLOR_TEMPERATURE, DPT_SCALING
from core.exceptions import CommandArgumentError, InvalidValueError


def _byte(value: float, full: float) -> int:
    return round(value * 255 / full)


def _unbyte(raw: int, full: float) -> float:
    return round(raw * full / 255, 1)


class ColorLightDevice(BaseDevice):
    TYPE = "color_light"

    def setup(self) -> None:
        self._warm = self.config.get_int("WarmKelvin", 2700)
        self._cold = self.config.get_int("ColdKelvin", 6500)
        if not 0 < self._warm < self._cold <= 0xFFFF:
            raise InvalidValueError(
                f"[{self.config.section_name}] WarmKelvin {self._warm} must be below ColdKelvin {self._cold}")
        self._level = self._in_range("Level", self.config.get_float("Level", 0.0), 0, 100, InvalidValueError)
        self._kelvin = int(self._in_range("Kelvin", self.config.get_int("Kelvin", self._warm),
                                          self._warm, self._cold, InvalidValueError))
        self._hue = self._in_range("Hue", self.config.get_float("Hue", 0.0), 0, 360, InvalidValueError)
        self._saturation = self._in_range("Saturation", self.config.get_float("Saturation", 0.0), 0, 100,
                                          InvalidValueError)
        self._on = self._level > 0
        self._last = self._level or 100.0

        self._status: dict[str, StatusPoint] = {}
        for key, name, dpt, on_write, getter in (
            ("", "on", DPT_BOOL, self.on_switch, lambda: self._on),
            ("Dim", "level", DPT_SCALING, self.on_dim, lambda: self._level),
            ("Kelvin", "kelvin", DPT_COLOR_TEMPERATURE, self.on_kelvin, lambda: self._kelvin),
            ("ColorTemp", "color_temp", DPT_SCALING, self.on_color_temp, self._cold_share),
            ("HSV", "hsv", DPT_COLOR_3BYTE, self.on_hsv, self._hsv),
        ):
            if f"Action{key}" in self.config:
                self.add(ActionPoint(f"action_{name}", self.config.get_ga(f"Action{key}"), dpt, on_write))
            if f"Status{key}" in self.config:
                self._status[name] = self.add(StatusPoint(name, self.config.get_ga(f"Status{key}"), dpt, getter))

    def _in_range(self, key: str, value: float, low: float, high: float, error) -> float:
        if not low <= value <= high:
            where = f"[{self.config.section_name}]" if error is InvalidValueError else "Command"
            raise error(f"{where} {key} {value} is outside {low}..{high}")
        return value

    def _cold_share(self) -> float:
        return (self._kelvin - self._warm) / (self._cold - self._warm) * 100

    def _hsv(self) -> tuple[int, int, int]:
        return _byte(self._hue, 360), _byte(self._saturation, 100), _byte(self._level, 100)

    def _switched(self, on: bool) -> dict:
        if not on:
            return {"on": False, "level": 0.0}
        return {} if self._on else {"on": True, "level": self._last}

    def _dimmed(self, level: float) -> dict:
        return {"on": level > 0, "level": level, **({"last": level} if level > 0 else {})}

    # --- bus -----------------------------------------------------------------
    def on_switch(self, value: bool) -> None:
        self._change(self._status.get("on"), **self._switched(bool(value)))

    def on_dim(self, level: float) -> None:
        self._change(self._status.get("level"), **self._dimmed(level))

    def on_kelvin(self, kelvin: int) -> None:
        self._change(self._status.get("kelvin"), kelvin=min(max(kelvin, self._warm), self._cold))

    def on_color_temp(self, share: float) -> None:
        self._change(self._status.get("color_temp"),
                     kelvin=round(self._warm + share / 100 * (self._cold - self._warm)))

    def on_hsv(self, hsv: tuple[int, int, int]) -> None:
        hue, saturation, value = hsv
        self._change(self._status.get("hsv"), hue=_unbyte(hue, 360), saturation=_unbyte(saturation, 100),
                     **self._dimmed(_unbyte(value, 100)))

    # --- local commands ------------------------------------------------------
    @local_command("toggle", description="Toggle on/off")
    def cmd_toggle(self) -> dict:
        return self._change(**self._switched(not self._on))

    @local_command("set", description="Set on/off (on brings back the last brightness)", args_schema={"on": bool})
    def cmd_set(self, on: bool) -> dict:
        return self._change(**self._switched(on))

    @local_command("set_level", description="Brightness 0..100 %", args_schema={"level": float})
    def cmd_set_level(self, level: float) -> dict:
        return self._change(**self._dimmed(self._in_range("level", level, 0, 100, CommandArgumentError)))

    @local_command("set_kelvin", description="Color temperature, K", args_schema={"kelvin": int})
    def cmd_set_kelvin(self, kelvin: int) -> dict:
        return self._change(kelvin=self._in_range("kelvin", kelvin, self._warm, self._cold, CommandArgumentError))

    @local_command("set_hsv", description="Hue 0..360°, saturation and brightness 0..100 %",
                   args_schema={"hue": float, "saturation": float, "level": float})
    def cmd_set_hsv(self, hue: float, saturation: float, level: float) -> dict:
        state = dict(hue=self._in_range("hue", hue, 0, 360, CommandArgumentError),
                     saturation=self._in_range("saturation", saturation, 0, 100, CommandArgumentError))
        return self._change(**state, **self._dimmed(self._in_range("level", level, 0, 100, CommandArgumentError)))

    # --- logic ---------------------------------------------------------------
    def _change(self, echo: StatusPoint | None = None, **state) -> dict:
        """Apply the new state, then send every status that changed and the echo."""
        before = {dp: dp.read() for dp in self._status.values()}
        for key, value in state.items():
            setattr(self, f"_{key}", value)
        for dp, old in before.items():
            if dp is echo or dp.read() != old:
                self.publish(dp)
        return self.state_snapshot()

    def state_snapshot(self) -> dict:
        return {"on": self._on, "level": self._level, "kelvin": self._kelvin, "hue": self._hue,
                "saturation": self._saturation}
