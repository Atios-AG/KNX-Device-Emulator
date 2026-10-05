"""Regression: the incoming xknx callback must be SYNCHRONOUS.

xknx calls telegram_received_cb without await (see telegram_queue.
_run_telegram_received_cbs). If it is made a coroutine, the telegrams are not
handled and RuntimeWarning 'coroutine was never awaited' is raised.

The outgoing half is checked without a network: xknx is replaced by a plain
queue and the telegrams the adapter puts there are inspected.
"""

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from core.address import GroupAddress
from core.bus_adapter import KNXIPBusAdapter
from core.config_loader import AppConfig, DeviceConfig, DeviceEntry
from core.device_manager import DeviceManager
from core.dpt import DPT_BOOL, DPT_SCALING, DPT_TEMPERATURE
from core.registry import DeviceRegistry


def test_incoming_callback_is_not_coroutine():
    # The main regression guard: the callback must not be async.
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

    # Write with a 1-bit value (DPTBinary) -> raw int
    adapter._on_xknx_telegram(_incoming("1/1/1", GroupValueWrite(DPTBinary(1))))
    # Write with a multi-byte value (DPTArray) -> raw bytes
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

    # our own outgoing telegram must not be handled
    adapter._on_xknx_telegram(
        Telegram(
            destination_address=XGA("1/1/1"),
            direction=TelegramDirection.OUTGOING,
            payload=GroupValueWrite(DPTBinary(1)),
        )
    )
    assert received == []


# --- outgoing ----------------------------------------------------------------

def _adapter_with_queue():
    pytest.importorskip("xknx")
    adapter = KNXIPBusAdapter({})
    adapter._xknx = SimpleNamespace(telegrams=asyncio.Queue())
    return adapter


def _sent(adapter):
    """Telegrams the adapter has put on the outgoing queue, oldest first."""
    queue = adapter._xknx.telegrams
    return [queue.get_nowait() for _ in range(queue.qsize())]


def test_one_bit_value_goes_out_as_a_binary_write():
    adapter = _adapter_with_queue()
    from xknx.dpt import DPTBinary
    from xknx.telegram import TelegramDirection
    from xknx.telegram.apci import GroupValueWrite

    asyncio.run(adapter.send_write(GroupAddress.from_string("2/7/1"), DPT_BOOL, True))

    (telegram,) = _sent(adapter)
    assert str(telegram.destination_address) == "2/7/1"
    assert telegram.direction is TelegramDirection.OUTGOING
    assert type(telegram.payload) is GroupValueWrite
    assert telegram.payload.value == DPTBinary(1)


def test_byte_values_go_out_as_an_array():
    adapter = _adapter_with_queue()
    from xknx.dpt import DPTArray
    from xknx.dpt import DPTTemperature as XTemperature

    async def scenario():
        await adapter.send_write(GroupAddress.from_string("2/7/2"), DPT_SCALING, 100.0)
        await adapter.send_write(GroupAddress.from_string("2/1/3"), DPT_TEMPERATURE, 21.5)

    asyncio.run(scenario())

    position, temperature = _sent(adapter)
    assert position.payload.value == DPTArray((255,))
    # the bytes of our own 9.001 codec are read back by the xknx one
    assert XTemperature.from_knx(temperature.payload.value) == 21.5


def test_response_and_write_use_different_services():
    adapter = _adapter_with_queue()
    from xknx.telegram.apci import GroupValueResponse, GroupValueWrite

    ga = GroupAddress.from_string("2/7/1")

    async def scenario():
        await adapter.send_response(ga, DPT_BOOL, False)
        await adapter.send_write(ga, DPT_BOOL, False)

    asyncio.run(scenario())

    response, write = _sent(adapter)
    assert type(response.payload) is GroupValueResponse
    assert type(write.payload) is GroupValueWrite


def test_scheduled_sends_reach_the_queue_in_order():
    adapter = _adapter_with_queue()
    from xknx.telegram.apci import GroupValueResponse, GroupValueWrite

    ga = GroupAddress.from_string("2/7/1")

    async def scenario():
        adapter.schedule_write(ga, DPT_BOOL, True)
        adapter.schedule_response(ga, DPT_BOOL, True)
        await asyncio.sleep(0)  # let the scheduled tasks run

    asyncio.run(scenario())

    assert [type(t.payload) for t in _sent(adapter)] == [GroupValueWrite, GroupValueResponse]


def test_device_status_reaches_the_wire_through_the_real_adapter():
    adapter = _adapter_with_queue()
    from xknx.dpt import DPTBinary
    from xknx.telegram.apci import GroupValueRead, GroupValueResponse, GroupValueWrite

    cfg = DeviceConfig("outlet0", {"type": "outlet", "Action": "1/1/1", "Status": "2/2/2"})
    reg = DeviceRegistry(); reg.discover("devices")
    mgr = DeviceManager(reg, adapter)
    mgr.build(AppConfig(knx={}, control={}, devices=[DeviceEntry("outlet0", "outlet", cfg)]))

    async def scenario():
        adapter._on_xknx_telegram(_incoming("1/1/1", GroupValueWrite(DPTBinary(1))))
        adapter._on_xknx_telegram(_incoming("2/2/2", GroupValueRead()))
        await asyncio.sleep(0)  # let the scheduled tasks run

    asyncio.run(scenario())

    status, answer = _sent(adapter)
    assert (str(status.destination_address), type(status.payload)) == ("2/2/2", GroupValueWrite)
    assert status.payload.value == DPTBinary(1)
    assert (str(answer.destination_address), type(answer.payload)) == ("2/2/2", GroupValueResponse)
    assert answer.payload.value == DPTBinary(1)
