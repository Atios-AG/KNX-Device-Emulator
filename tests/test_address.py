import pytest

from core.address import GroupAddress
from core.exceptions import InvalidValueError


def test_parse_and_roundtrip():
    ga = GroupAddress.from_string("1/1/1")
    assert ga.levels == (1, 1, 1)
    assert str(ga) == "1/1/1"


def test_equality_and_hash():
    a = GroupAddress.from_string("2/2/2")
    b = GroupAddress.from_string("2/2/2")
    assert a == b
    assert hash(a) == hash(b)
    assert {a: 1}[b] == 1


@pytest.mark.parametrize("bad", ["1/1", "32/0/0", "0/8/0", "0/0/256", "x/y/z"])
def test_invalid(bad):
    with pytest.raises(InvalidValueError):
        GroupAddress.from_string(bad)
