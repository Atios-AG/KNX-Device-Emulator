"""Virtual KNX RGBW light: on/off and one brightness object per LED channel.

Built from the objects of a KNX LED controller in single channel control (MDT
AKD-0x24x.02, technical manual 5.3.2, table 39, and the object list): on/off
(objects 64, status 80) and red, green, blue and white each as 0..100 %
(DPT 5.001, objects 3 / 19 / 35 / 51, status 5 / 21 / 37 / 53). Without a
white address it is an RGB light. Every object is optional, active when its
group address is set.

Switching on brings back the last channel values (the first time every
channel at 100 %), off sets every channel to 0 % and keeps them for the next
on. A channel above 0 % switches on, the last channel going to 0 % switches
off. A status is sent when its value changes and in reply to its own command.
Local commands: `toggle`, `set` (on=), `set_rgbw` (red=, green=, blue=, white=).

Config:
    [strip_living]
    type        = rgbw_light
    Action      = 1/6/1     ; optional, on/off (DPT 1.001)
    Status      = 1/6/2     ; optional, on/off status
    ActionRed   = 1/6/3     ; optional, red 0..100 % (DPT 5.001)
    StatusRed   = 1/6/4     ; optional
    ActionGreen = 1/6/5     ; optional
    StatusGreen = 1/6/6     ; optional
    ActionBlue  = 1/6/7     ; optional
    StatusBlue  = 1/6/8     ; optional
    ActionWhite = 1/6/9     ; optional, without it an RGB light
    StatusWhite = 1/6/10    ; optional
    Red         = 0         ; initial channel values 0..100 %, on when one is above 0
    Green       = 0
    Blue        = 0
    White       = 0
"""

from core.datapoint import ActionPoint, StatusPoint
from core.device import BaseDevice, local_command
from core.dpt import DPT_BOOL, DPT_SCALING
from core.exceptions import CommandArgumentError, InvalidValueError

CHANNELS = ("red", "green", "blue", "white")


class RgbwLightDevice(BaseDevice):
    TYPE = "rgbw_light"

    def setup(self) -> None:
        self._channels = CHANNELS if any(f"{k}White" in self.config for k in ("Action", "Status")) else CHANNELS[:3]
        self._level = {ch: self._in_range(ch.title(), self.config.get_float(ch.title(), 0.0), InvalidValueError)
                       for ch in self._channels}
        self._on = any(self._level.values())
        self._last = dict(self._level) if self._on else {ch: 100.0 for ch in self._channels}

        self._status: dict[str, StatusPoint] = {}
        for key, name, dpt, on_write, getter in (
            ("", "on", DPT_BOOL, self.on_switch, lambda: self._on),
            *((ch.title(), ch, DPT_SCALING, lambda v, ch=ch: self.on_channel(ch, v),
               lambda ch=ch: self._level[ch]) for ch in self._channels),
        ):
            if f"Action{key}" in self.config:
                self.add(ActionPoint(f"action_{name}", self.config.get_ga(f"Action{key}"), dpt, on_write))
            if f"Status{key}" in self.config:
                self._status[name] = self.add(StatusPoint(name, self.config.get_ga(f"Status{key}"), dpt, getter))

    def _in_range(self, key: str, value: float, error) -> float:
        if not 0 <= value <= 100:
            where = f"[{self.config.section_name}]" if error is InvalidValueError else "Command"
            raise error(f"{where} {key} {value} is outside 0..100")
        return value

    def _switched(self, on: bool) -> dict:
        if not on:
            return {"on": False, "level": {ch: 0.0 for ch in self._channels}}
        return {} if self._on else {"on": True, "level": dict(self._last)}

    def _set(self, level: dict) -> dict:
        on = any(level.values())
        return {"on": on, "level": level, **({"last": dict(level)} if on else {})}

    # --- bus -----------------------------------------------------------------
    def on_switch(self, value: bool) -> None:
        self._change(self._status.get("on"), **self._switched(bool(value)))

    def on_channel(self, channel: str, value: float) -> None:
        self._change(self._status.get(channel), **self._set({**self._level, channel: value}))

    # --- local commands ------------------------------------------------------
    @local_command("toggle", description="Toggle on/off")
    def cmd_toggle(self) -> dict:
        return self._change(**self._switched(not self._on))

    @local_command("set", description="Set on/off (on brings back the last channel values)",
                   args_schema={"on": bool})
    def cmd_set(self, on: bool) -> dict:
        return self._change(**self._switched(on))

    @local_command("set_rgbw", description="Red, green, blue and white 0..100 % (white 0 on an RGB light)",
                   args_schema={"red": float, "green": float, "blue": float, "white": float})
    def cmd_set_rgbw(self, red: float, green: float, blue: float, white: float) -> dict:
        given = dict(zip(CHANNELS, (red, green, blue, white)))
        if "white" not in self._channels and white:
            raise CommandArgumentError("Command white: this light has no white channel")
        return self._change(**self._set({ch: self._in_range(ch, given[ch], CommandArgumentError)
                                         for ch in self._channels}))

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
        return {"on": self._on, **self._level}
