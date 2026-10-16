"""Alarm binary sensor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import PowernessConfigEntry
from .entity import PowernessEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowernessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    async_add_entities([PowernessAlarmSensor(entry.runtime_data, "alarm")])


class PowernessAlarmSensor(PowernessEntity, BinarySensorEntity):
    """On when the battery reports any alarm flag.

    The meaning of the single flags is not documented yet, they are exposed
    as attributes so they can be mapped later.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        """Return True if an alarm is active."""
        alarms = self.coordinator.data.alarms
        return None if alarms is None else any(alarms.values())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the active alarm tags."""
        alarms = self.coordinator.data.alarms
        if alarms is None:
            return None
        return {"active_codes": [f"0x{tag:02x}" for tag, val in alarms.items() if val]}
