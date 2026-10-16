"""Start / end times of the four schedule periods (DP 103)."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
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
    """Set up the time entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        PowernessSlotTime(coordinator, index, is_start)
        for index in range(parser.MAX_PERIODS)
        for is_start in (True, False)
    )


def to_hhmm(value: time) -> str:
    """Format a time for the schedule (minute resolution)."""
    return f"{value.hour:02d}:{value.minute:02d}"


class PowernessSlotTime(PowernessEntity, TimeEntity):
    """Start or end of one schedule period."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: PowernessCoordinator, index: int, is_start: bool) -> None:
        """Initialize the entity."""
        part = "start" if is_start else "end"
        super().__init__(coordinator, f"slot{index + 1}_{part}")
        self._attr_translation_key = f"slot_{part}"
        self._attr_translation_placeholders = {"slot": str(index + 1)}
        self._index = index
        self._is_start = is_start

    @property
    def native_value(self) -> time:
        """Return the time of the slot."""
        slot = self.coordinator.slots[self._index]
        hour, minute = (
            int(part) for part in (slot.start if self._is_start else slot.end).split(":")
        )
        return time(hour, minute)

    async def async_set_value(self, value: time) -> None:
        """Change the slot; written to the battery when the slot is active."""
        hhmm = to_hhmm(value)
        if self._is_start:
            await self.coordinator.async_update_slot(self._index, start=hhmm)
        else:
            await self.coordinator.async_update_slot(self._index, end=hhmm)
