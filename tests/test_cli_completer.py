"""Tests for the context-aware CLI completion."""

import pytest

pytest.importorskip("prompt_toolkit")

from prompt_toolkit.document import Document  # noqa: E402

from core.config_loader import AppConfig, DeviceConfig, DeviceEntry  # noqa: E402
from core.control import ControlInterface  # noqa: E402
from core.control.transports.cli import _build_completer  # noqa: E402
from core.device_manager import DeviceManager  # noqa: E402
from core.registry import DeviceRegistry  # noqa: E402
from tests.fakes import FakeBusAdapter  # noqa: E402


def _completer():
    cfg = DeviceConfig("outlet0", {
        "type": "outlet", "Action": "1/1/1", "Status": "2/2/2",
    })
    reg = DeviceRegistry(); reg.discover("devices")
    mgr = DeviceManager(reg, FakeBusAdapter())
    mgr.build(AppConfig(knx={}, control={}, devices=[
        DeviceEntry("outlet0", "outlet", cfg)
    ]))
    return _build_completer(ControlInterface(mgr))


def _texts(comp, text):
    doc = Document(text, len(text))
    return [c.text for c in comp.get_completions(doc, None)]


def test_first_level_has_devices_and_builtins():
    out = _texts(_completer(), "")
    assert "outlet0" in out
    assert {"list", "describe", "help", "quit"} <= set(out)


def test_prefix_filter():
    assert _texts(_completer(), "out") == ["outlet0"]


def test_command_level():
    out = _texts(_completer(), "outlet0 ")
    assert "toggle" in out and "set" in out


def test_argument_names():
    out = _texts(_completer(), "outlet0 set ")
    assert out == ["on="]


def test_bool_value_hint():
    out = _texts(_completer(), "outlet0 set on=")
    assert out == ["true", "false"]


def test_describe_completes_devices():
    out = _texts(_completer(), "describe ")
    assert "outlet0" in out


def test_unknown_device_no_completions():
    assert _texts(_completer(), "ghost ") == []
