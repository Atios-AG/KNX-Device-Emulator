import os
import textwrap

import pytest

from core.config_loader import ConfigLoader
from core.exceptions import ConfigError, InvalidValueError, MissingOptionError


def _write(tmp_path, text):
    path = tmp_path / "config.ini"
    path.write_text(textwrap.dedent(text))
    return str(path)


def test_load_ok(tmp_path):
    path = _write(tmp_path, """
        [knx]
        connection = tunneling
        gateway_ip = 1.2.3.4

        [outlet0]
        type = outlet
        Action = 1/1/1
        Status = 2/2/2
        Inverted = True
    """)
    cfg = ConfigLoader.load(path)
    assert cfg.knx["gateway_ip"] == "1.2.3.4"
    assert len(cfg.devices) == 1
    dev = cfg.devices[0]
    assert dev.name == "outlet0"
    assert dev.type == "outlet"
    assert dev.config.get_bool("Inverted") is True
    assert str(dev.config.get_ga("Action")) == "1/1/1"


def test_missing_type(tmp_path):
    path = _write(tmp_path, """
        [outlet0]
        Action = 1/1/1
    """)
    with pytest.raises(MissingOptionError):
        ConfigLoader.load(path)


def test_no_devices(tmp_path):
    path = _write(tmp_path, """
        [knx]
        connection = routing
    """)
    with pytest.raises(ConfigError):
        ConfigLoader.load(path)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        ConfigLoader.load(str(tmp_path / "nope.ini"))


def test_get_float(tmp_path):
    path = _write(tmp_path, """
        [garage0]
        type = garage_door
        Action = 1/7/1
        TravelSec = 12.5
        Bad = fast
    """)
    cfg = ConfigLoader.load(path).devices[0].config
    assert cfg.get_float("TravelSec") == 12.5
    assert cfg.get_float("Missing", 10.0) == 10.0
    assert cfg.get_float("Missing") is None
    with pytest.raises(InvalidValueError):
        cfg.get_float("Bad")


def test_inline_comments_and_percent_signs(tmp_path):
    path = _write(tmp_path, """
        [knx]
        gateway_ip = 1.2.3.4        ; the gateway
        [dimmer0]
        type      = dimmer          # inline comment with '#'
        Action    = 1/2/1           ; on/off (DPT 1.001)
        ActionDim = 1/2/2           ; level 0..100 % (DPT 5.001)
        Status    = 2/2/1
        StatusDim = 2/2/2
        Inverted  = True            ; 0 % = closed
    """)
    cfg = ConfigLoader.load(path)
    assert cfg.knx["gateway_ip"] == "1.2.3.4"
    dev = cfg.devices[0].config
    assert dev.get("type") == "dimmer"
    assert str(dev.get_ga("ActionDim")) == "1/2/2"
    assert dev.get_bool("Inverted") is True


def test_example_config_loads():
    example = os.path.join(os.path.dirname(__file__), "..", "config.example.ini")
    cfg = ConfigLoader.load(example)
    names = {d.name: d.type for d in cfg.devices}
    assert names["outlet0"] == "outlet"
    assert names["garage_door0"] == "garage_door"
    assert str(names and cfg.devices[0].config.get_ga("Action")) == "1/1/1"
