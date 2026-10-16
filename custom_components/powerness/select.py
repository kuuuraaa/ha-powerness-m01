"""Mode (off / charge / discharge) of the four schedule periods."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import parser
from .coordinator import PowernessConfigEntry, PowernessCoordinator
from .entity import PowernessEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowernessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the select entities."""
    coordinator = entry.runtime_data
    async_add_entities(PowernessSlotMode(coordinator, index) for index in range(parser.MAX_PERIODS))


class PowernessSlotMode(PowernessEntity, SelectEntity):
    """What the battery does in one schedule period."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = parser.SLOT_MODES

    def __init__(self, coordinator: PowernessCoordinator, index: int) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, f"slot{index + 1}_mode")
        self._attr_translation_key = "slot_mode"
        self._attr_translation_placeholders = {"slot": str(index + 1)}
        self._index = index

    @property
    def current_option(self) -> str:
        """Return the mode of the slot."""
        return self.coordinator.slots[self._index].mode

    async def async_select_option(self, option: str) -> None:
        """Change the mode and write the schedule."""
        await self.coordinator.async_update_slot(self._index, mode=option)
