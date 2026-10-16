"""Actions of the integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from . import parser
from .const import DOMAIN
from .time import to_hhmm

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_PERIODS = "periods"

PERIOD_SCHEMA = vol.Schema(
    {
        vol.Required("start"): cv.time,
        vol.Required("end"): cv.time,
        vol.Required("mode"): vol.In(list(parser.MODE_FLAGS)),
    }
)

SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_PERIODS): vol.All(
            cv.ensure_list, [PERIOD_SCHEMA], vol.Length(min=1, max=parser.MAX_PERIODS)
        ),
    }
)


async def _async_set_schedule(call: ServiceCall) -> None:
    """Replace the schedule with up to four periods."""
    entry = call.hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError("The battery is not set up or not loaded")
    periods = [
        parser.SchedulePeriod(
            to_hhmm(period["start"]), to_hhmm(period["end"]), parser.MODE_FLAGS[period["mode"]]
        )
        for period in call.data[ATTR_PERIODS]
    ]
    await entry.runtime_data.async_set_schedule(periods)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""
    hass.services.async_register(
        DOMAIN, "set_schedule", _async_set_schedule, schema=SET_SCHEDULE_SCHEMA
    )
