"""Common fixtures."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
import functools
import sys
from unittest.mock import patch

import pytest

if sys.platform == "win32":
    # The windows event loop needs a socket pair, which pytest_socket would block
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerness import protocol
from custom_components.powerness.const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    DOMAIN,
)
from homeassistant.const import CONF_HOST

from .const import DEVICE_ID, LOCAL_KEY
from .fake_device import FakeBattery


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading the integration."""


@pytest.fixture
async def fake_battery() -> AsyncGenerator[FakeBattery]:
    """A fake battery on localhost; the coordinator is pointed at it."""
    battery = FakeBattery()
    await battery.start()
    device = functools.partial(protocol.TuyaDevice, port=battery.port)
    with patch("custom_components.powerness.coordinator.TuyaDevice", device):
        yield battery
    await battery.stop()


@pytest.fixture
def no_discovery() -> Generator[None]:
    """Never wait for UDP broadcasts."""
    with (
        patch("custom_components.powerness.coordinator.async_discover", return_value={}),
        patch("custom_components.powerness.config_flow.async_discover", return_value={}),
    ):
        yield


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry for the fake battery."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Balkonkraftwerk Batterie",
        unique_id=DEVICE_ID,
        data={
            CONF_HOST: "127.0.0.1",
            CONF_DEVICE_ID: DEVICE_ID,
            CONF_LOCAL_KEY: LOCAL_KEY,
            CONF_PROTOCOL_VERSION: "3.4",
        },
    )
