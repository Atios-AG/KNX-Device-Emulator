import pytest

from core.dpt import DPT_BOOL, DPT_SCALING, DPT_TEMPERATURE, dpt_from_string
from core.exceptions import DPTError


def test_bool_roundtrip():
    assert DPT_BOOL.encode(True) == 1
    assert DPT_BOOL.encode(False) == 0
    assert DPT_BOOL.decode(1) is True
    assert DPT_BOOL.decode(0) is False


def test_scaling_roundtrip():
    assert DPT_SCALING.encode(0) == bytes([0])
    assert DPT_SCALING.encode(100) == bytes([255])
    mid = DPT_SCALING.encode(50)
    assert DPT_SCALING.decode(mid) == pytest.approx(50, abs=1)


def test_scaling_out_of_range():
    with pytest.raises(DPTError):
        DPT_SCALING.encode(150)


@pytest.mark.parametrize("value", [0.0, 21.0, -5.0, 37.6, -273.0, 100.0])
def test_temperature_roundtrip(value):
    raw = DPT_TEMPERATURE.encode(value)
    assert len(raw) == 2
    assert DPT_TEMPERATURE.decode(raw) == pytest.approx(value, abs=0.1)


def test_dpt_from_string():
    assert dpt_from_string("1.001") is DPT_BOOL
    with pytest.raises(DPTError):
        dpt_from_string("99.999")
