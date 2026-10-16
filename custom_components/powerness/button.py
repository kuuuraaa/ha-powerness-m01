"""Button to request live data."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import PowernessConfigEntry
from .entity import PowernessEntity
from .protocol import TuyaError

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowernessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button."""
    async_add_entities([PowernessWakeButton(entry.runtime_data, "request_live_data")])


class PowernessWakeButton(PowernessEntity, ButtonEntity):
    """Sends the wake command that makes the battery stream live data."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        """Send the wake command."""
        try:
            await self.coordinator.async_request_live_data()
        except TuyaError as err:
            raise HomeAssistantError(f"Cannot reach the battery: {err}") from err
