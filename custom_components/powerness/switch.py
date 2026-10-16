"""Charge / discharge switches."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DP_CHARGER_SWITCH, DP_DISCHARGE_SWITCH
from .coordinator import PowernessConfigEntry, PowernessCoordinator
from .entity import PowernessEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowernessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            PowernessSwitch(coordinator, "charging", DP_CHARGER_SWITCH),
            PowernessSwitch(coordinator, "discharging", DP_DISCHARGE_SWITCH),
        ]
    )


class PowernessSwitch(PowernessEntity, SwitchEntity):
    """A boolean data point."""

    def __init__(self, coordinator: PowernessCoordinator, key: str, dp: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, key)
        self._dp = dp

    @property
    def is_on(self) -> bool | None:
        """Return the switch state."""
        value = self.coordinator.data.dps.get(self._dp)
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on."""
        await self.coordinator.async_set_dp(self._dp, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self.coordinator.async_set_dp(self._dp, False)
