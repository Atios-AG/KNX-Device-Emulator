"""Virtual air quality sensor.

A set of read-only readings (each one is a separate Status on the bus). A full
counterpart of the Matter `air_quality_sensor` device: every sensor is enabled
independently — if its Group Address is set in the config, the sensor is
present, otherwise it is absent (like the `cfg->sensor_*_enabled` flags in the
firmware).

The "Matter cluster -> KNX DPT" mapping:

  | Reading   | DPT   | Unit     | Range / meaning                      |
  |-----------|-------|----------|--------------------------------------|
  | AQI       | 5.010 | —        | 0 = Good … 255 = Extremely Poor      |
  | CH2O      | 9.008 | ppm      | formaldehyde                         |
  | TVOC      | 9.008 | ppm      | volatile organic compounds           |
  | PM1.0     | 9.030 | µg/m³    | particulate matter 1.0               |
  | PM2.5     | 9.030 | µg/m³    | particulate matter 2.5               |
  | PM10      | 9.030 | µg/m³    | particulate matter 10                |
  | CO2       | 9.008 | ppm      | carbon dioxide                       |

The readings change only "locally" (from the panel) — the sensor accepts no
commands from the bus. Every sensor is a separate control command with a single
argument `set`, so that it can be picked with TAB in the CLI:
`air_quality0 co2 set=400`. Optionally (CycleSec) the device cyclically
re-broadcasts the current values to the bus, the way a hardware KNX sensor does.

Config (any set of sensors — the one whose Status is set is present):
    [air0]
    type       = air_quality_sensor
    StatusAQI   = 3/0/1            ; AQI  (DPT 5.010)
    StatusCH2O  = 3/0/2            ; CH2O (DPT 9.008, ppm)
    StatusTVOC  = 3/0/3            ; TVOC (DPT 9.008, ppm)
    StatusPM1   = 3/0/4            ; PM1.0 (DPT 9.030)
    StatusPM2_5 = 3/0/5            ; PM2.5 (DPT 9.030)
    StatusPM10  = 3/0/6            ; PM10 (DPT 9.030)
    StatusCO2   = 3/0/7            ; CO2  (DPT 9.008, ppm)
    AQI = 50                       ; initial values (optional)
    CO2 = 400
    CycleSec = 60                  ; cyclic broadcast period (0/absent — off)

Set a reading from the CLI:
    knx> air_quality0 co2 set=400
    knx> air_quality0 aqi set=42
"""

from __future__ import annotations

import asyncio
import logging

from core.datapoint import StatusPoint
from core.device import BaseDevice, CommandSpec
from core.dpt import (
    DPT,
    DPT_AIR_QUALITY_PPM,
    DPT_CONCENTRATION_UGM3,
    DPT_UCOUNT,
)
from core.exceptions import CommandArgumentError, UnknownCommandError

log = logging.getLogger(__name__)


# --- description of the sensor set -------------------------------------------
# id -> (GA key in the config, initial value key, DPT, integer?)
_SENSORS: dict[str, tuple[str, str, DPT, bool]] = {
    "aqi":   ("StatusAQI",   "AQI",   DPT_UCOUNT,             True),
    "ch2o":  ("StatusCH2O",  "CH2O",  DPT_AIR_QUALITY_PPM,    False),
    "tvoc":  ("StatusTVOC",  "TVOC",  DPT_AIR_QUALITY_PPM,    False),
    "pm1":   ("StatusPM1",   "PM1",   DPT_CONCENTRATION_UGM3, False),
    "pm2_5": ("StatusPM2_5", "PM2_5", DPT_CONCENTRATION_UGM3, False),
    "pm10":  ("StatusPM10",  "PM10",  DPT_CONCENTRATION_UGM3, False),
    "co2":   ("StatusCO2",   "CO2",   DPT_AIR_QUALITY_PPM,    False),
}


class AirQualitySensorDevice(BaseDevice):
    TYPE = "air_quality_sensor"

    def setup(self) -> None:
        self._cycle = self.config.get_int("CycleSec", 0)
        self._task = None

        self._values: dict[str, float] = {}        # the current reading by id
        self._is_int: dict[str, bool] = {}         # the reading type (AQI is int)
        self._points: dict[str, StatusPoint] = {}  # id -> Status point

        # The commands are registered per instance: every sensor device has its
        # own set of sensors (unlike the class-level @local_command). Every
        # sensor is a separate command with a single `set` argument, so that in
        # the CLI it is picked with TAB instead of being typed by hand:
        # <dev> <sensor> set=<value>
        commands: dict[str, CommandSpec] = {}

        for sid, (ga_key, init_key, dpt, is_int) in _SENSORS.items():
            if ga_key not in self.config:
                continue  # the sensor is not configured — absent, as in Matter
            self._is_int[sid] = is_int
            self._values[sid] = self._cast(sid, self.config.get(init_key, 0))
            point = self.add(
                StatusPoint(sid, self.config.get_ga(ga_key), dpt,
                            lambda s=sid: self._values[s])
            )
            self._points[sid] = point
            unit = dpt.unit or ("0..255" if is_int else "")
            commands[sid] = CommandSpec(
                name=sid,
                description=f"Set the {sid.upper()} reading" + (f" ({unit})" if unit else ""),
                args_schema={"set": float},
            )

        if not self._points:
            raise CommandArgumentError(
                f"[{self.name}] air_quality_sensor: no sensor is configured "
                f"(at least one of {[v[0] for v in _SENSORS.values()]} was expected)"
            )

        # the per-instance command dict shadows the empty class-level one
        self._local_commands = commands

    # --- local commands (panel) ----------------------------------------------
    def dispatch_local_command(self, name: str, args: dict | None = None) -> dict:
        """Every command = a sensor name; the single `set` argument is the value.

        Example:  air_quality0 co2 set=400
        """
        spec = self._local_commands.get(name)
        if spec is None:
            raise UnknownCommandError(
                f"Device '{self.name}' does not support the command '{name}'. "
                f"Available sensors: {sorted(self._local_commands)}"
            )
        kwargs = self._coerce_args(spec, dict(args or {}))
        self._values[name] = self._cast(name, kwargs["set"])
        self.log.info("panel -> sensor '%s' set=%s", name, self._values[name])
        self.publish(self._points[name])
        return self.state_snapshot()

    # --- helpers -------------------------------------------------------------
    def _cast(self, sid: str, value):
        try:
            return int(round(float(value))) if self._is_int[sid] else round(float(value), 2)
        except (TypeError, ValueError) as exc:
            raise CommandArgumentError(
                f"Sensor '{sid}': the value must be a number, got {value!r}"
            ) from exc

    # --- cyclic broadcast (like a hardware KNX sensor) -----------------------
    async def start(self) -> None:
        if self._cycle:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._cycle)
            for point in self._points.values():
                self.publish(point)
