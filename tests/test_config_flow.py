"""Tests for the config flow."""

from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerness.const import (
    CONF_DEVICE_ID,
    CONF_KEEP_ALIVE,
    CONF_LOCAL_KEY,
    CONF_PRODUCT_ID,
    CONF_PROTOCOL_VERSION,
    CONF_USER_CODE,
    DOMAIN,
)
from custom_components.powerness.protocol import TuyaAuthError, TuyaConnectionError
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .const import DEVICE_ID, LOCAL_KEY

LOGIN_INFO = {
    "t": 1,
    "uid": "uid",
    "expire_time": 7200,
    "access_token": "a",
    "refresh_token": "r",
    "terminal_id": "term",
    "endpoint": "https://apigw.tuyaeu.com",
    "username": "user",
}


def _cloud_device(device_id: str, category: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=device_id,
        name=name,
        local_key=LOCAL_KEY,
        category=category,
        product_id="mwllseqnhzar191l" if category == "cnsb" else "other",
        product_name="Micro Battery",
        sub=False,
    )


@pytest.fixture(autouse=True)
def no_setup() -> Generator[None]:
    """Do not set up the created entries."""
    with patch("custom_components.powerness.async_setup_entry", return_value=True):
        yield


@pytest.fixture
def cloud(hass: HomeAssistant) -> Generator[MagicMock]:
    """Mock the Smart Life login and device list."""
    devices = [
        _cloud_device(DEVICE_ID, "cnsb", "Balkonkraftwerk Batterie"),
        _cloud_device("plug", "cz", "Steckdose"),
    ]
    with (
        patch("custom_components.powerness.config_flow.LoginControl") as login_cls,
        patch("custom_components.powerness.config_flow.Manager") as manager_cls,
    ):
        login = login_cls.return_value
        login.qr_code.return_value = {"success": True, "result": {"qrcode": "abc"}}
        login.login_result.return_value = (True, LOGIN_INFO)
        manager_cls.return_value.device_map = {d.id: d for d in devices}
        yield login


@pytest.fixture
def validate() -> Generator[AsyncMock]:
    """Mock the local connection test."""
    with patch("custom_components.powerness.config_flow.async_validate", return_value={}) as mock:
        yield mock


@pytest.fixture
def discover() -> Generator[AsyncMock]:
    """Mock LAN discovery finding the battery."""
    with patch(
        "custom_components.powerness.config_flow.async_discover",
        return_value={DEVICE_ID: {"gwId": DEVICE_ID, "ip": "192.168.1.50", "version": "3.4"}},
    ) as mock:
        yield mock


async def _start_cloud(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "cloud"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USER_CODE: "code123"}
    )
    assert result["step_id"] == "scan"
    return await hass.config_entries.flow.async_configure(result["flow_id"], {})


@pytest.mark.usefixtures("cloud", "discover")
async def test_cloud_flow(hass: HomeAssistant, validate: AsyncMock) -> None:
    """QR login finds the battery and its IP, no further questions."""
    result = await _start_cloud(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Balkonkraftwerk Batterie"
    assert result["data"] == {
        CONF_DEVICE_ID: DEVICE_ID,
        CONF_LOCAL_KEY: LOCAL_KEY,
        CONF_PRODUCT_ID: "mwllseqnhzar191l",
        CONF_USER_CODE: "code123",
        CONF_HOST: "192.168.1.50",
        CONF_PROTOCOL_VERSION: "3.4",
    }
    validate.assert_awaited_once_with("192.168.1.50", DEVICE_ID, LOCAL_KEY, "3.4")


@pytest.mark.usefixtures("cloud", "validate")
async def test_cloud_flow_not_discovered(hass: HomeAssistant) -> None:
    """Without a broadcast the user enters the IP."""
    with patch("custom_components.powerness.config_flow.async_discover", return_value={}):
        result = await _start_cloud(hass)
    assert result["step_id"] == "locate"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "10.0.0.9", CONF_PROTOCOL_VERSION: "3.4"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "10.0.0.9"


@pytest.mark.usefixtures("discover")
async def test_cloud_flow_login_failed(hass: HomeAssistant, cloud: MagicMock) -> None:
    """A failed QR login shows the scan step again with an error."""
    cloud.login_result.return_value = (False, {"msg": "nope"})
    result = await _start_cloud(hass)
    assert result["step_id"] == "scan"
    assert result["errors"] == {"base": "login_error"}


@pytest.mark.usefixtures("cloud", "discover")
@pytest.mark.parametrize(
    ("error", "expected"),
    [(TuyaConnectionError, "cannot_connect"), (TuyaAuthError, "invalid_auth")],
)
async def test_cloud_flow_connect_errors(
    hass: HomeAssistant, validate: AsyncMock, error: type[Exception], expected: str
) -> None:
    """Connection problems end in the locate step, which can recover."""
    validate.side_effect = error
    result = await _start_cloud(hass)
    assert result["step_id"] == "locate"
    assert result["errors"] == {"base": expected}
    validate.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_PROTOCOL_VERSION: "3.4"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("discover", "validate")
async def test_manual_flow(hass: HomeAssistant) -> None:
    """Manual setup discovers the IP when it is left empty."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Akku",
            CONF_DEVICE_ID: DEVICE_ID,
            CONF_LOCAL_KEY: LOCAL_KEY,
            CONF_PROTOCOL_VERSION: "3.4",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Akku"
    assert result["data"][CONF_HOST] == "192.168.1.50"


@pytest.mark.usefixtures("validate")
async def test_manual_flow_not_found(hass: HomeAssistant) -> None:
    """Without IP and broadcast the user is asked for the IP."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    with patch("custom_components.powerness.config_flow.async_discover", return_value={}):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Akku",
                CONF_DEVICE_ID: DEVICE_ID,
                CONF_LOCAL_KEY: LOCAL_KEY,
                CONF_PROTOCOL_VERSION: "3.4",
            },
        )
    assert result["errors"] == {"base": "not_found"}


@pytest.mark.usefixtures("cloud", "discover", "validate")
async def test_already_configured(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """The same battery cannot be added twice."""
    config_entry.add_to_hass(hass)
    result = await _start_cloud(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("cloud")
async def test_reauth(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Reauth logs in again and stores the new local key."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_LOCAL_KEY: "old"}
    )
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "cloud"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USER_CODE: "code123"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_LOCAL_KEY] == LOCAL_KEY


async def test_options(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Keep-alive can be switched off."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_KEEP_ALIVE: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_KEEP_ALIVE: False}
