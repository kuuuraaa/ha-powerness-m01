"""Base entity for the battery."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DP_FIRMWARE
from .coordinator import PowernessCoordinator


class PowernessEntity(CoordinatorEntity[PowernessCoordinator]):
    """Entity bound to the battery device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PowernessCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        self._attr_translation_key = key
        firmware = coordinator.data.dps.get(DP_FIRMWARE)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name=coordinator.config_entry.title,
            manufacturer="Powerness / EPP",
            model="M01 / BES 1.5 kWh",
            sw_version=firmware if isinstance(firmware, str) else None,
            serial_number=_serial(coordinator),
        )


def _serial(coordinator: PowernessCoordinator) -> str | None:
    records = coordinator.data.dc_records
    if len(records) > 1:
        return records[1].serial
    if (bms := coordinator.data.bms) is not None:
        return bms.serial
    return None
