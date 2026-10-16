"""Config flow: Smart Life QR login to fetch the local key, then local setup.

The QR login steps are adapted from the Home Assistant core Tuya integration
(https://github.com/home-assistant/core, Apache-2.0).
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from tuya_sharing import LoginControl, Manager
import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_ID,
    CONF_KEEP_ALIVE,
    CONF_LOCAL_KEY,
    CONF_PRODUCT_ID,
    CONF_PROTOCOL_VERSION,
    CONF_USER_CODE,
    DEFAULT_PROTOCOL_VERSION,
    DOMAIN,
    KNOWN_PRODUCT_IDS,
    PROTOCOL_VERSIONS,
    TUYA_CATEGORY,
    TUYA_CLIENT_ID,
    TUYA_SCHEMA,
)
from .discovery import async_discover
from .protocol import TuyaAuthError, TuyaDevice, TuyaError

_LOGGER = logging.getLogger(__name__)

CONF_DEVICE = "device"


async def async_validate(host: str, device_id: str, local_key: str, version: str) -> dict[str, Any]:
    """Connect once and read all data points."""
    device = TuyaDevice(host, device_id, local_key, version)
    try:
        await device.connect()
        return await device.query()
    finally:
        await device.close()


def _is_battery(device: Any) -> bool:
    return (
        getattr(device, "category", None) == TUYA_CATEGORY
        or getattr(device, "product_id", None) in KNOWN_PRODUCT_IDS
    )


class PowernessConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._login = LoginControl()
        self._user_code = ""
        self._qr_code = ""
        self._cloud_devices: dict[str, Any] = {}
        self._device: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PowernessOptionsFlow:
        """Return the options flow."""
        return PowernessOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose between Smart Life login and manual setup."""
        return self.async_show_menu(step_id="user", menu_options=["cloud", "manual"])

    # Smart Life login -------------------------------------------------------

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the Smart Life user code."""
        errors: dict[str, str] = {}
        placeholders = {"msg": ""}
        if user_input is not None:
            ok, response = await self._async_get_qr_code(user_input[CONF_USER_CODE])
            if ok:
                return await self.async_step_scan()
            errors["base"] = "login_error"
            placeholders["msg"] = str(response.get("msg", "Unknown error"))
        return self.async_show_form(
            step_id="cloud",
            data_schema=vol.Schema({vol.Required(CONF_USER_CODE, default=self._user_code): str}),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_scan(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the QR code and wait for the user to confirm the login."""
        errors: dict[str, str] = {}
        if user_input is not None:
            ok, info = await self.hass.async_add_executor_job(
                self._login.login_result, self._qr_code, TUYA_CLIENT_ID, self._user_code
            )
            if ok:
                return await self._async_load_devices(info)
            errors["base"] = "login_error"
            await self._async_get_qr_code(self._user_code)
        return self.async_show_form(
            step_id="scan",
            data_schema=vol.Schema(
                {
                    vol.Optional("qr"): selector.QrCodeSelector(
                        selector.QrCodeSelectorConfig(
                            data=f"tuyaSmart--qrLogin?token={self._qr_code}",
                            scale=5,
                            error_correction_level=selector.QrErrorCorrectionLevel.QUARTILE,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def _async_get_qr_code(self, user_code: str) -> tuple[bool, dict[str, Any]]:
        response = await self.hass.async_add_executor_job(
            self._login.qr_code, TUYA_CLIENT_ID, TUYA_SCHEMA, user_code
        )
        if ok := bool(response.get("success")):
            self._user_code = user_code
            self._qr_code = response["result"]["qrcode"]
        return ok, response

    async def _async_load_devices(self, info: dict[str, Any]) -> ConfigFlowResult:
        token = {
            key: info[key] for key in ("t", "uid", "expire_time", "access_token", "refresh_token")
        }
        manager = Manager(
            TUYA_CLIENT_ID,
            self._user_code,
            info["terminal_id"],
            info["endpoint"],
            token,
        )
        await self.hass.async_add_executor_job(manager.update_device_cache)
        devices = [d for d in manager.device_map.values() if not getattr(d, "sub", False)]
        batteries = [d for d in devices if _is_battery(d)]
        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            match = next((d for d in devices if d.id == entry.unique_id), None)
            if match is None:
                return self.async_abort(reason="device_not_found")
            return self.async_update_reload_and_abort(
                entry,
                data={
                    **entry.data,
                    CONF_LOCAL_KEY: match.local_key,
                    CONF_USER_CODE: self._user_code,
                },
            )
        candidates = batteries or devices
        if not candidates:
            return self.async_abort(reason="no_devices")
        self._cloud_devices = {d.id: d for d in candidates}
        if len(batteries) == 1:
            return await self._async_use_cloud_device(batteries[0])
        return await self.async_step_pick()

    async def async_step_pick(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick the battery if the account has several candidates."""
        if user_input is not None:
            return await self._async_use_cloud_device(self._cloud_devices[user_input[CONF_DEVICE]])
        options = [
            selector.SelectOptionDict(
                value=d.id, label=f"{d.name} ({getattr(d, 'product_name', '')})"
            )
            for d in self._cloud_devices.values()
        ]
        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def _async_use_cloud_device(self, device: Any) -> ConfigFlowResult:
        await self.async_set_unique_id(device.id)
        self._abort_if_unique_id_configured()
        self._device = {
            CONF_NAME: device.name,
            CONF_DEVICE_ID: device.id,
            CONF_LOCAL_KEY: device.local_key,
            CONF_PRODUCT_ID: getattr(device, "product_id", None),
            CONF_USER_CODE: self._user_code,
        }
        return await self.async_step_locate()

    # Local connection -------------------------------------------------------

    async def async_step_locate(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Find the device on the LAN, ask for the IP if that fails."""
        errors: dict[str, str] = {}
        if user_input is None:
            found = (await async_discover(self._device[CONF_DEVICE_ID])).get(
                self._device[CONF_DEVICE_ID]
            )
            if found and found.get("ip"):
                version = str(found.get("version", DEFAULT_PROTOCOL_VERSION))
                if version not in PROTOCOL_VERSIONS:
                    version = DEFAULT_PROTOCOL_VERSION
                result = await self._async_try_create(found["ip"], version, errors)
                if result is not None:
                    return result
            user_input = {}
        else:
            result = await self._async_try_create(
                user_input[CONF_HOST], user_input[CONF_PROTOCOL_VERSION], errors
            )
            if result is not None:
                return result
        return self.async_show_form(
            step_id="locate",
            data_schema=self._host_schema(user_input),
            errors=errors,
            description_placeholders={"name": self._device[CONF_NAME]},
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manual setup with device ID and local key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()
            self._device = {
                CONF_NAME: user_input[CONF_NAME],
                CONF_DEVICE_ID: user_input[CONF_DEVICE_ID],
                CONF_LOCAL_KEY: user_input[CONF_LOCAL_KEY],
            }
            host = user_input.get(CONF_HOST)
            if not host:
                found = (await async_discover(user_input[CONF_DEVICE_ID])).get(
                    user_input[CONF_DEVICE_ID]
                )
                host = found.get("ip") if found else None
            if host:
                result = await self._async_try_create(
                    host, user_input[CONF_PROTOCOL_VERSION], errors
                )
                if result is not None:
                    return result
            else:
                errors["base"] = "not_found"
        user_input = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default=user_input.get(CONF_NAME, "Balkonkraftwerk Batterie")
                ): str,
                vol.Required(CONF_DEVICE_ID, default=user_input.get(CONF_DEVICE_ID, "")): str,
                vol.Required(CONF_LOCAL_KEY, default=user_input.get(CONF_LOCAL_KEY, "")): str,
            }
        ).extend(self._host_schema(user_input, host_required=False).schema)
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    @staticmethod
    def _host_schema(user_input: dict[str, Any], host_required: bool = True) -> vol.Schema:
        host_key = vol.Required if host_required else vol.Optional
        return vol.Schema(
            {
                host_key(CONF_HOST, default=user_input.get(CONF_HOST, "")): str,
                vol.Required(
                    CONF_PROTOCOL_VERSION,
                    default=user_input.get(CONF_PROTOCOL_VERSION, DEFAULT_PROTOCOL_VERSION),
                ): vol.In(PROTOCOL_VERSIONS),
            }
        )

    async def _async_try_create(
        self, host: str, version: str, errors: dict[str, str]
    ) -> ConfigFlowResult | None:
        try:
            await async_validate(
                host, self._device[CONF_DEVICE_ID], self._device[CONF_LOCAL_KEY], version
            )
        except TuyaAuthError:
            errors["base"] = "invalid_auth"
            return None
        except TuyaError:
            errors["base"] = "cannot_connect"
            return None
        except Exception:
            _LOGGER.exception("Unexpected error while connecting")
            errors["base"] = "unknown"
            return None
        name = self._device.pop(CONF_NAME)
        return self.async_create_entry(
            title=name,
            data={**self._device, CONF_HOST: host, CONF_PROTOCOL_VERSION: version},
        )

    # Reauth: the local key changes when the battery is paired again ---------

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start re-authentication."""
        self._user_code = entry_data.get(CONF_USER_CODE, "")
        return await self.async_step_cloud()


class PowernessOptionsFlow(OptionsFlow):
    """Options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_KEEP_ALIVE,
                        default=self.config_entry.options.get(CONF_KEEP_ALIVE, True),
                    ): bool,
                }
            ),
        )
