"""Diagnostics: raw data points help decoding unknown fields."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import parser
from .const import CONF_LOCAL_KEY, CONF_USER_CODE
from .coordinator import PowernessConfigEntry

TO_REDACT = {CONF_LOCAL_KEY, CONF_USER_CODE}


def _hex(value: Any) -> str | None:
    data = parser.decode_b64(value)
    return None if data is None else data.hex(" ")


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PowernessConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "connected": entry.runtime_data.device.connected,
        "dc_updated": data.dc_updated.isoformat() if data.dc_updated else None,
        "dps": data.dps,
        "dps_hex": {dp: hexed for dp, val in data.dps.items() if (hexed := _hex(val))},
    }
