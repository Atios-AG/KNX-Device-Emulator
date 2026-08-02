import textwrap

import pytest

from core.config_loader import ConfigLoader
from core.exceptions import ConfigError, MissingOptionError


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
