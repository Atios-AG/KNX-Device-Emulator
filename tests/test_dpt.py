import pytest

from core.dpt import (
    DPT_AIR_QUALITY_PPM,
    DPT_BOOL,
    DPT_COLOR_3BYTE,
    DPT_COLOR_TEMPERATURE,
    DPT_CONCENTRATION_UGM3,
    DPT_SCALING,
    DPT_TEMPERATURE,
    DPT_UCOUNT,
    dpt_from_string,
)
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


def test_ucount_roundtrip():
    assert DPT_UCOUNT.encode(0) == bytes([0])
    assert DPT_UCOUNT.encode(255) == bytes([255])
    assert DPT_UCOUNT.encode(50.4) == bytes([50])  # rounding
    assert DPT_UCOUNT.decode(bytes([200])) == 200
    assert DPT_UCOUNT.decode(7) == 7  # a bare int is accepted too


def test_ucount_out_of_range():
    with pytest.raises(DPTError):
        DPT_UCOUNT.encode(256)
    with pytest.raises(DPTError):
        DPT_UCOUNT.encode(-1)


@pytest.mark.parametrize("dpt", [DPT_AIR_QUALITY_PPM, DPT_CONCENTRATION_UGM3])
@pytest.mark.parametrize("value", [0.0, 12.5, 400.0, 65535.0])
def test_concentration_roundtrip(dpt, value):
    raw = dpt.encode(value)
    assert len(raw) == 2
    assert dpt.decode(raw) == pytest.approx(value, rel=0.01, abs=1.0)


def test_concentration_rejects_negative():
    with pytest.raises(DPTError):
        DPT_AIR_QUALITY_PPM.encode(-1)
    with pytest.raises(DPTError):
        DPT_CONCENTRATION_UGM3.encode(-0.5)


def test_air_quality_dpt_ids():
    assert DPT_UCOUNT.dpt_id == "5.010"
    assert DPT_AIR_QUALITY_PPM.dpt_id == "9.008"
    assert DPT_CONCENTRATION_UGM3.dpt_id == "9.030"


def test_dpt_from_string():
    assert dpt_from_string("1.001") is DPT_BOOL
    assert dpt_from_string("5.010") is DPT_UCOUNT
    assert dpt_from_string("9.008") is DPT_AIR_QUALITY_PPM
    assert dpt_from_string("9.030") is DPT_CONCENTRATION_UGM3
    with pytest.raises(DPTError):
        dpt_from_string("99.999")


def test_color_temperature_is_two_bytes_big_endian():
    assert DPT_COLOR_TEMPERATURE.encode(4000) == bytes([0x0F, 0xA0])
    assert DPT_COLOR_TEMPERATURE.decode(bytes([0x0A, 0x8E])) == 2702
    assert dpt_from_string("7.600") is DPT_COLOR_TEMPERATURE


@pytest.mark.parametrize("bad", [-1, 65536, "warm", None])
def test_color_temperature_out_of_range(bad):
    with pytest.raises(DPTError):
        DPT_COLOR_TEMPERATURE.encode(bad)


def test_color_temperature_needs_two_bytes():
    with pytest.raises(DPTError):
        DPT_COLOR_TEMPERATURE.decode(bytes([1]))


def test_color_3byte_roundtrip():
    assert DPT_COLOR_3BYTE.encode((85, 255, 128)) == bytes([85, 255, 128])
    assert DPT_COLOR_3BYTE.decode(bytes([85, 255, 128])) == (85, 255, 128)
    assert dpt_from_string("232.600") is DPT_COLOR_3BYTE


@pytest.mark.parametrize("bad", [(1, 2), (256, 0, 0), (-1, 0, 0), None, "red"])
def test_color_3byte_rejects_anything_but_three_bytes(bad):
    with pytest.raises(DPTError):
        DPT_COLOR_3BYTE.encode(bad)


def test_color_3byte_needs_three_bytes():
    with pytest.raises(DPTError):
        DPT_COLOR_3BYTE.decode(bytes([1, 2]))
