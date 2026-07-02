"""Регрессия: входящий callback xknx должен быть СИНХРОННЫМ.

xknx вызывает telegram_received_cb без await (см. telegram_queue.
_run_telegram_received_cbs). Если сделать его корутиной — телеграммы не
обрабатываются и сыплется RuntimeWarning 'coroutine was never awaited'.
"""

import inspect

import pytest

from core.bus_adapter import KNXIPBusAdapter


def test_incoming_callback_is_not_coroutine():
    # Главная защита от регрессии: callback не должен быть async.
    assert not inspect.iscoroutinefunction(KNXIPBusAdapter._on_xknx_telegram)


def _incoming(ga, payload):
    from xknx.telegram import GroupAddress as XGA
    from xknx.telegram import Telegram, TelegramDirection

    return Telegram(
        destination_address=XGA(ga),
        direction=TelegramDirection.INCOMING,
        payload=payload,
    )


def test_incoming_telegrams_parsed():
    pytest.importorskip("xknx")
    from xknx.dpt import DPTArray, DPTBinary
    from xknx.telegram.apci import GroupValueRead, GroupValueWrite

    adapter = KNXIPBusAdapter({})
    received = []
    adapter.set_telegram_handler(lambda ga, kind, raw: received.append((str(ga), kind, raw)))

    # Write с 1-битным значением (DPTBinary) -> raw int
    adapter._on_xknx_telegram(_incoming("1/1/1", GroupValueWrite(DPTBinary(1))))
    # Write с многобайтным значением (DPTArray) -> raw bytes
    adapter._on_xknx_telegram(_incoming("1/1/2", GroupValueWrite(DPTArray((0, 200)))))
    # Read -> raw None
    adapter._on_xknx_telegram(_incoming("2/2/2", GroupValueRead()))

    assert received[0] == ("1/1/1", "write", 1)
    assert received[1] == ("1/1/2", "write", bytes([0, 200]))
    assert received[2] == ("2/2/2", "read", None)


def test_outgoing_telegrams_ignored():
    pytest.importorskip("xknx")
    from xknx.dpt import DPTBinary
    from xknx.telegram import GroupAddress as XGA
    from xknx.telegram import Telegram, TelegramDirection
    from xknx.telegram.apci import GroupValueWrite

    adapter = KNXIPBusAdapter({})
    received = []
    adapter.set_telegram_handler(lambda *a: received.append(a))

    # собственная исходящая телеграмма не должна обрабатываться
    adapter._on_xknx_telegram(
        Telegram(
            destination_address=XGA("1/1/1"),
            direction=TelegramDirection.OUTGOING,
            payload=GroupValueWrite(DPTBinary(1)),
        )
    )
    assert received == []
