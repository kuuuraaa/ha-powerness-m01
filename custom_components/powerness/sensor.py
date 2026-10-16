"""Sensors for the battery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import parser
from .const import DP_CHARGER_SWITCH, DP_DISCHARGE_SWITCH
from .coordinator import PowernessConfigEntry, PowernessCoordinator, PowernessData
from .entity import PowernessEntity

PARALLEL_UPDATES = 0

# Samples further apart than this are not integrated (device was asleep)
MAX_INTEGRATION_GAP = 300


# Explicit comparisons: max(-0.0, 0.0) would return -0.0 and show as "-0 W"
def _positive(value: float | None) -> float | None:
    if value is None:
        return None
    return value if value > 0 else 0.0


def _negative(value: float | None) -> float | None:
    if value is None:
        return None
    return -value if value < 0 else 0.0


@dataclass(frozen=True, kw_only=True)
class PowernessSensorDescription(SensorEntityDescription):
    """Describes a battery sensor."""

    value_fn: Callable[[PowernessData], Any]
    attr_fn: Callable[[PowernessData], dict[str, Any] | None] = lambda d: None


SCHEDULE_MODES = ["charge", "discharge", "charge_discharge", "off", "permanent"]
BATTERY_STATES = [*parser.BCU_STATES.values(), "unknown"]


def _schedule_mode(data: PowernessData) -> str | None:
    # The permanent charge / discharge switches override the schedule; the
    # app only applies the schedule while both are off
    if data.dps.get(DP_CHARGER_SWITCH) or data.dps.get(DP_DISCHARGE_SWITCH):
        return "permanent"
    if not (periods := data.schedule):
        return None
    now = dt_util.now().strftime("%H:%M")
    for period in periods:
        if period.contains(now):
            if period.charge and period.discharge:
                return "charge_discharge"
            if period.charge:
                return "charge"
            if period.discharge:
                return "discharge"
            return "off"
    return "off"


def _schedule_attrs(data: PowernessData) -> dict[str, Any] | None:
    if not (periods := data.schedule):
        return None
    return {
        "periods": [
            {"start": p.start, "end": p.end, "charge": p.charge, "discharge": p.discharge}
            for p in periods
        ]
    }


def _battery_state(data: PowernessData) -> str | None:
    if (code := data.bcu_state) is None:
        return None
    return parser.BCU_STATES.get(code, "unknown")


def _battery_state_attrs(data: PowernessData) -> dict[str, Any]:
    # Raw values that are not decoded yet, to map them later
    attrs: dict[str, Any] = {"code": data.bcu_state, "status_pv": data.status_pv}
    if (stack := data.stack) is not None:
        attrs["heartbeat_tail"] = stack.raw_tail
    if (bms := data.bms) is not None:
        attrs["cell_index_a"] = bms.values.get(parser.BMS_CELL_A)
        attrs["cell_index_b"] = bms.values.get(parser.BMS_CELL_B)
    return attrs


SENSORS: tuple[PowernessSensorDescription, ...] = (
    PowernessSensorDescription(
        key="soc",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.soc,
    ),
    PowernessSensorDescription(
        key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.voltage,
    ),
    PowernessSensorDescription(
        key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.current,
    ),
    PowernessSensorDescription(
        key="charge_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: _positive(d.power),
    ),
    PowernessSensorDescription(
        key="discharge_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: _negative(d.power),
    ),
    PowernessSensorDescription(
        key="pv_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.pv_current,
    ),
    PowernessSensorDescription(
        key="pv_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.pv_power,
    ),
    PowernessSensorDescription(
        key="pv_energy_total",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda d: d.pv_total,
    ),
    PowernessSensorDescription(
        key="lifetime_charged",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda d: d.lifetime_charged,
    ),
    PowernessSensorDescription(
        key="lifetime_discharged",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda d: d.lifetime_discharged,
    ),
    PowernessSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.temperature,
    ),
    PowernessSensorDescription(
        key="battery_state",
        device_class=SensorDeviceClass.ENUM,
        options=BATTERY_STATES,
        value_fn=_battery_state,
        attr_fn=_battery_state_attrs,
    ),
    PowernessSensorDescription(
        key="schedule",
        device_class=SensorDeviceClass.ENUM,
        options=SCHEDULE_MODES,
        value_fn=_schedule_mode,
        attr_fn=_schedule_attrs,
    ),
    PowernessSensorDescription(
        key="last_live_data",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.dc_updated,
    ),
)


@dataclass(frozen=True, kw_only=True)
class PowernessEnergyDescription(SensorEntityDescription):
    """Describes an energy sensor integrated from a power value."""

    power_fn: Callable[[PowernessData], float | None]


ENERGY_SENSORS: tuple[PowernessEnergyDescription, ...] = (
    PowernessEnergyDescription(
        key="energy_charged",
        power_fn=lambda d: _positive(d.power),
    ),
    PowernessEnergyDescription(
        key="energy_discharged",
        power_fn=lambda d: _negative(d.power),
    ),
    PowernessEnergyDescription(
        key="pv_energy",
        power_fn=lambda d: d.pv_power,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowernessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        PowernessSensor(coordinator, description) for description in SENSORS
    ]
    entities.extend(
        PowernessEnergySensor(coordinator, description) for description in ENERGY_SENSORS
    )
    async_add_entities(entities)


class PowernessSensor(PowernessEntity, SensorEntity):
    """A sensor computed from the decoded data."""

    entity_description: PowernessSensorDescription

    def __init__(
        self, coordinator: PowernessCoordinator, description: PowernessSensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        return self.entity_description.attr_fn(self.coordinator.data)


class PowernessEnergySensor(PowernessEntity, RestoreSensor):
    """Energy in kWh, integrated (trapezoidal) from live power samples."""

    entity_description: PowernessEnergyDescription
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3

    def __init__(
        self, coordinator: PowernessCoordinator, description: PowernessEnergyDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_native_value = 0.0
        self._last_sample: tuple[datetime, float] | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the counter."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            try:
                self._attr_native_value = float(last.native_value or 0)
            except (TypeError, ValueError):
                self._attr_native_value = 0.0

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        stamp = data.dc_updated
        power = self.entity_description.power_fn(data)
        if stamp is None or power is None:
            return
        if self._last_sample is not None and stamp > self._last_sample[0]:
            prev_stamp, prev_power = self._last_sample
            seconds = (stamp - prev_stamp).total_seconds()
            if seconds <= MAX_INTEGRATION_GAP:
                kwh = (prev_power + power) / 2 * seconds / 3_600_000
                self._attr_native_value = float(self._attr_native_value or 0) + kwh
        if self._last_sample is None or stamp > self._last_sample[0]:
            self._last_sample = (stamp, power)
        self.async_write_ha_state()
