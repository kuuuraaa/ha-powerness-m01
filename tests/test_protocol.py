"""Tests for the local protocol client against the fake battery."""

import asyncio
import json
from unittest.mock import patch

import pytest

from custom_components.powerness import protocol
from custom_components.powerness.discovery import UDP_KEY, decode_broadcast
from custom_components.powerness.protocol import AESCipher, TuyaAuthError, TuyaDevice, pack_frame

from .const import DC_DATA_CHARGING, DEVICE_ID, LOCAL_KEY, STATUS_DPS
from .fake_device import FakeBattery


async def _wait_for(check) -> None:
    for _ in range(100):
        if check():
            return
        await asyncio.sleep(0.01)


@pytest.fixture
async def battery():
    """Start a fake battery."""
    fake = FakeBattery()
    await fake.start()
    yield fake
    await fake.stop()


async def test_query_and_push(battery: FakeBattery) -> None:
    """Handshake, query, write and pushed status all work over 3.4."""
    pushed: list[dict] = []
    device = TuyaDevice(
        "127.0.0.1", DEVICE_ID, LOCAL_KEY, "3.4", on_status=pushed.append, port=battery.port
    )
    await device.connect()
    try:
        assert await device.query() == {k: v for k, v in STATUS_DPS.items() if k != "103"}
        await device.request_dps([103])
        await _wait_for(lambda: pushed)
        assert pushed.pop() == {"103": STATUS_DPS["103"]}
        await device.heartbeat()
        await device.set_dps({"1": "AQEBAQE="})
        await _wait_for(lambda: pushed)
        assert battery.received == [{"updatedps": [103]}, {"1": "AQEBAQE="}]
        assert pushed == [{"10": DC_DATA_CHARGING}]
    finally:
        await device.close()
    assert not device.connected


async def test_wrong_key(battery: FakeBattery) -> None:
    """A wrong key gets no handshake answer and raises an auth error."""
    device = TuyaDevice("127.0.0.1", DEVICE_ID, "fedcba9876543210", "3.4", port=battery.port)
    with patch.object(protocol, "RESPONSE_TIMEOUT", 0.2), pytest.raises(TuyaAuthError):
        await device.connect()
    assert not device.connected


async def test_disconnect_callback(battery: FakeBattery) -> None:
    """Losing the connection is reported."""
    lost = asyncio.Event()
    device = TuyaDevice(
        "127.0.0.1", DEVICE_ID, LOCAL_KEY, "3.4", on_disconnect=lost.set, port=battery.port
    )
    await device.connect()
    await battery.stop()
    await asyncio.wait_for(lost.wait(), 2)
    assert not device.connected


def test_decode_broadcast() -> None:
    """Encrypted 3.4 broadcasts are decoded."""
    info = {"ip": "192.168.1.50", "gwId": DEVICE_ID, "version": "3.4"}
    payload = b"\x00\x00\x00\x00" + AESCipher(UDP_KEY).encrypt(json.dumps(info).encode())
    datagram = pack_frame(0, 0x13, payload, None)
    assert decode_broadcast(datagram) == info
    assert decode_broadcast(b"garbage") is None
