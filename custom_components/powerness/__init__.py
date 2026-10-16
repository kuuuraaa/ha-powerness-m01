"""The Powerness M01 / EPP BES battery integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import CONF_DEVICE_ID, DOMAIN, PLATFORMS
from .coordinator import PowernessConfigEntry, PowernessCoordinator, storage_key
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Entities of earlier versions that no longer exist
REMOVED_ENTITIES = (
    ("sensor", "battery_power"),
    ("sensor", "operating_state"),
    ("time", "charge_start"),
    ("time", "charge_end"),
    ("time", "discharge_start"),
    ("time", "discharge_end"),
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PowernessConfigEntry) -> bool:
    """Set up the battery from a config entry."""
    _remove_old_entities(hass, entry)
    coordinator = PowernessCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_start()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PowernessConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: PowernessConfigEntry) -> None:
    """Delete the remembered data points."""
    await Store(hass, 1, storage_key(entry.entry_id)).async_remove()


def _remove_old_entities(hass: HomeAssistant, entry: PowernessConfigEntry) -> None:
    registry = er.async_get(hass)
    for domain, key in REMOVED_ENTITIES:
        unique_id = f"{entry.data[CONF_DEVICE_ID]}_{key}"
        if entity_id := registry.async_get_entity_id(domain, DOMAIN, unique_id):
            registry.async_remove(entity_id)
