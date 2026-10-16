"""Connection handling and data model for the battery."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import parser
from .const import (
    CONF_DEVICE_ID,
    CONF_KEEP_ALIVE,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    DEFAULT_PROTOCOL_VERSION,
    DOMAIN,
    DP_ALARM_MESSAGE,
    DP_BATTERY_DC_DATA,
    DP_BCU_INFO,
    DP_BMS_MESSAGE,
    DP_GET_TERMINAL_DATA,
    DP_PV_CURRENT,
    DP_PV_TOTAL,
    DP_STACK_INFO,
    DP_STATUS_PV,
    DP_TEMPERATURE,
    DP_TIME_SCHEDULE,
    KEEP_ALIVE_CHECK,
    PERSISTED_DPS,
    POLL_INTERVAL,
    STALE_AFTER,
    WAKE_PAYLOAD,
)
from .discovery import async_discover
from .protocol import TuyaAuthError, TuyaDevice, TuyaError

_LOGGER = logging.getLogger(__name__)

AUTH_FAILURES_BEFORE_REAUTH = 3

type PowernessConfigEntry = ConfigEntry[PowernessCoordinator]


def _hex_or_raw(value: Any) -> Any:
    data = parser.decode_b64(value)
    return value if data is None else data.hex(" ")


def storage_key(entry_id: str) -> str:
    """Key of the store that remembers rarely reported data points."""
    return f"{DOMAIN}.{entry_id}"


@dataclass(slots=True)
class PowernessData:
    """Decoded state of the battery."""

    dps: dict[str, Any] = field(default_factory=dict)
    dc_updated: datetime | None = None

    @property
    def dc_records(self) -> list[parser.DcRecord]:
        """Heartbeat records: index 0 is the stack, the rest are packs."""
        return parser.parse_dc_data(self.dps.get(DP_BATTERY_DC_DATA))

    @property
    def stack(self) -> parser.DcRecord | None:
        """The whole-stack heartbeat record."""
        records = self.dc_records
        return records[0] if records else None

    @property
    def bms(self) -> parser.TlvMessage | None:
        """Decoded ``bms_message``."""
        return parser.parse_tlv(self.dps.get(DP_BMS_MESSAGE))

    @property
    def stack_info(self) -> parser.TlvMessage | None:
        """Decoded ``stack_info``."""
        return parser.parse_tlv(self.dps.get(DP_STACK_INFO))

    @property
    def alarms(self) -> dict[int, int] | None:
        """Alarm flags by tag."""
        msg = parser.parse_tlv(self.dps.get(DP_ALARM_MESSAGE))
        return None if msg is None else msg.values

    @property
    def soc(self) -> int | None:
        """State of charge in %."""
        if (stack := self.stack) is not None:
            return stack.soc
        if (info := self.stack_info) is not None and parser.STACK_SOC in info.values:
            return info.values[parser.STACK_SOC]
        if (bms := self.bms) is not None:
            return bms.values.get(parser.BMS_SOC)
        return None

    @property
    def bcu(self) -> parser.TlvMessage | None:
        """Decoded ``bcu_info_hex``."""
        return parser.parse_tlv(self.dps.get(DP_BCU_INFO))

    @property
    def bcu_state(self) -> int | None:
        """Battery state code from ``bcu_info_hex``."""
        bcu = self.bcu
        return None if bcu is None else bcu.values.get(parser.BCU_STATE)

    @property
    def schedule(self) -> list[parser.SchedulePeriod]:
        """Time schedule periods."""
        return parser.parse_schedule(self.dps.get(DP_TIME_SCHEDULE))

    @property
    def status_pv(self) -> str | None:
        """Raw ``status_pv`` as hex."""
        data = parser.decode_b64(self.dps.get(DP_STATUS_PV))
        return None if data is None else data.hex(" ")

    @property
    def voltage(self) -> float | None:
        """Battery voltage in V."""
        if (stack := self.stack) is not None:
            return stack.voltage
        if (bms := self.bms) is not None and parser.BMS_VOLTAGE in bms.values:
            return bms.values[parser.BMS_VOLTAGE] / 10
        return None

    @property
    def current(self) -> float | None:
        """Battery current in A, positive while charging."""
        if (stack := self.stack) is not None:
            return stack.current
        if (bms := self.bms) is not None:
            raw = parser.tlv_signed16(bms, parser.BMS_CURRENT)
            return None if raw is None else raw / 10
        return None

    @property
    def power(self) -> float | None:
        """Battery power in W, positive while charging."""
        if self.voltage is None or self.current is None:
            return None
        return round(self.voltage * self.current, 1)

    @property
    def pv_current(self) -> float | None:
        """PV current in A."""
        raw = self.dps.get(DP_PV_CURRENT)
        return raw / 10 if isinstance(raw, int) else None

    @property
    def pv_power(self) -> float | None:
        """PV power in W (PV current on the battery side times voltage)."""
        if self.pv_current is None or self.voltage is None:
            return None
        return round(self.pv_current * self.voltage, 1)

    @property
    def pv_total(self) -> float | None:
        """Lifetime PV energy in kWh."""
        raw = self.dps.get(DP_PV_TOTAL)
        return raw / 10 if isinstance(raw, int) else None

    @property
    def temperature(self) -> int | None:
        """Temperature in °C."""
        raw = self.dps.get(DP_TEMPERATURE)
        return raw if isinstance(raw, int) else None

    def _stack_counter(self, tag: int) -> float | None:
        if (info := self.stack_info) is None or tag not in info.values:
            return None
        return info.values[tag] / 10

    @property
    def lifetime_charged(self) -> float | None:
        """Lifetime charged energy reported by the device in kWh."""
        return self._stack_counter(parser.STACK_ENERGY_CHARGED)

    @property
    def lifetime_discharged(self) -> float | None:
        """Lifetime discharged energy reported by the device in kWh."""
        return self._stack_counter(parser.STACK_ENERGY_DISCHARGED)


class PowernessCoordinator(DataUpdateCoordinator[PowernessData]):
    """Keeps the local connection alive and distributes pushed data."""

    config_entry: PowernessConfigEntry

    def __init__(self, hass: HomeAssistant, entry: PowernessConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=POLL_INTERVAL),
            always_update=True,
        )
        self.device_id: str = entry.data[CONF_DEVICE_ID]
        self.device = self._create_device(entry.data[CONF_HOST])
        self.data = PowernessData()
        self._last_wake: datetime | None = None
        self._auth_failures = 0
        self._requested_missing = False
        self._unsub_keep_alive: CALLBACK_TYPE | None = None
        self.store: Store[dict[str, Any]] = Store(hass, 1, storage_key(entry.entry_id))
        self.slots: list[parser.ScheduleSlot] = [parser.ScheduleSlot()] * parser.MAX_PERIODS

    async def async_load(self) -> None:
        """Restore data points the device only reports when they change."""
        stored = await self.store.async_load()
        if not isinstance(stored, dict):
            return
        # 0.2.1 stored the data points at the top level
        dps = stored.get("dps", stored)
        self.data.dps.update({dp: dps[dp] for dp in PERSISTED_DPS if dp in dps})
        slots = [
            parser.ScheduleSlot(**slot)
            for slot in stored.get("slots", [])
            if isinstance(slot, dict) and slot.get("mode") in parser.SLOT_MODES
        ]
        if slots:
            self.slots = (slots + self.slots)[: parser.MAX_PERIODS]
        self.slots = parser.sync_slots(self.slots, self.data.schedule)

    def _create_device(self, host: str) -> TuyaDevice:
        return TuyaDevice(
            host,
            self.device_id,
            self.config_entry.data[CONF_LOCAL_KEY],
            self.config_entry.data.get(CONF_PROTOCOL_VERSION, DEFAULT_PROTOCOL_VERSION),
            on_status=self._handle_status,
            on_disconnect=self._handle_disconnect,
        )

    @property
    def keep_alive(self) -> bool:
        """Return True if live data should be requested automatically."""
        return self.config_entry.options.get(CONF_KEEP_ALIVE, True)

    async def async_start(self) -> None:
        """Start the keep-alive timer."""
        self._unsub_keep_alive = async_track_time_interval(
            self.hass,
            self._async_keep_alive,
            timedelta(seconds=KEEP_ALIVE_CHECK),
            name=f"{DOMAIN} keep-alive",
        )

    async def async_shutdown(self) -> None:
        """Stop timers and close the connection."""
        if self._unsub_keep_alive:
            self._unsub_keep_alive()
            self._unsub_keep_alive = None
        await self.device.close()
        await super().async_shutdown()

    async def _async_update_data(self) -> PowernessData:
        try:
            if not self.device.connected:
                await self._async_connect()
            dps = await self.device.query()
        except TuyaAuthError as err:
            await self.device.close()
            # A busy device can miss a handshake, only ask for a new key
            # when it keeps failing
            self._auth_failures += 1
            if self._auth_failures >= AUTH_FAILURES_BEFORE_REAUTH:
                raise ConfigEntryAuthFailed(str(err)) from err
            raise UpdateFailed(str(err)) from err
        except TuyaError as err:
            await self.device.close()
            raise UpdateFailed(str(err)) from err
        self._auth_failures = 0
        self._merge(dps)
        await self._async_request_missing(dps)
        return self.data

    async def _async_request_missing(self, dps: dict[str, Any]) -> None:
        # The battery leaves e.g. the schedule out of the full query
        missing = [int(dp) for dp in PERSISTED_DPS if dp not in dps]
        if not missing or self._requested_missing:
            return
        self._requested_missing = True
        try:
            await self.device.request_dps(missing)
        except TuyaError as err:
            _LOGGER.debug("Requesting DPs %s failed: %s", missing, err)

    async def _async_connect(self) -> None:
        try:
            await self.device.connect()
        except TuyaAuthError:
            raise
        except TuyaError:
            # The IP may have changed, look for the device on the LAN
            found = (await async_discover(self.device_id)).get(self.device_id)
            if not found or found.get("ip") == self.device.host:
                raise
            _LOGGER.info("Battery moved to %s", found["ip"])
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_HOST: found["ip"]},
            )
            self.device = self._create_device(found["ip"])
            await self.device.connect()
        self._requested_missing = False
        await self.async_request_live_data()

    async def async_request_live_data(self) -> None:
        """Ask the device to stream live data (what the app does when opened)."""
        self._last_wake = dt_util.utcnow()
        await self.device.set_dps({DP_GET_TERMINAL_DATA: WAKE_PAYLOAD})

    async def async_set_dp(self, dp: str, value: Any) -> None:
        """Write a data point and update the local state optimistically."""
        try:
            await self.device.set_dps({dp: value})
        except TuyaError as err:
            raise HomeAssistantError(f"Cannot reach the battery: {err}") from err
        self._merge({dp: value})
        self.async_set_updated_data(self.data)

    async def async_set_schedule(self, periods: list[parser.SchedulePeriod]) -> None:
        """Write the time schedule (DP 103)."""
        try:
            value = parser.encode_schedule(periods)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_set_dp(DP_TIME_SCHEDULE, value)

    async def _async_keep_alive(self, now: datetime) -> None:
        if not self.keep_alive or not self.device.connected:
            return
        if self.data.dc_updated and (now - self.data.dc_updated).total_seconds() < STALE_AFTER:
            return
        if self._last_wake and (now - self._last_wake).total_seconds() < STALE_AFTER:
            return
        try:
            await self.async_request_live_data()
        except TuyaError as err:
            _LOGGER.debug("Wake request failed: %s", err)

    def _merge(self, dps: dict[str, Any]) -> None:
        if DP_BATTERY_DC_DATA in dps:
            self.data.dc_updated = dt_util.utcnow()
        changed = any(dp in dps and self.data.dps.get(dp) != dps[dp] for dp in PERSISTED_DPS)
        self.data.dps.update(dps)
        if DP_TIME_SCHEDULE in dps:
            self.slots = parser.sync_slots(self.slots, self.data.schedule)
        if changed:
            self.store.async_delay_save(self._stored_data, 5)

    def _stored_data(self) -> dict[str, Any]:
        return {
            "dps": {dp: self.data.dps[dp] for dp in PERSISTED_DPS if dp in self.data.dps},
            "slots": [
                {"start": slot.start, "end": slot.end, "mode": slot.mode} for slot in self.slots
            ],
        }

    async def async_update_slot(
        self,
        index: int,
        start: str | None = None,
        end: str | None = None,
        mode: str | None = None,
    ) -> None:
        """Change one schedule slot; writes the schedule if it affects it."""
        old = self.slots[index]
        new = parser.ScheduleSlot(start or old.start, end or old.end, mode or old.mode)
        slots = [*self.slots]
        slots[index] = new
        if parser.active_periods(slots) != parser.active_periods(self.slots):
            periods = parser.active_periods(slots)
            if not periods:
                raise HomeAssistantError(
                    "At least one period must stay active. To stop the schedule, "
                    "use the permanent charge / discharge switches."
                )
            previous, self.slots = self.slots, slots
            try:
                await self.async_set_schedule(periods)
            except HomeAssistantError:
                self.slots = previous
                raise
        else:
            # Times of a slot that is off are only remembered
            self.slots = slots
            self.async_set_updated_data(self.data)
        self.store.async_delay_save(self._stored_data, 5)

    @callback
    def _handle_status(self, dps: dict[str, Any]) -> None:
        if _LOGGER.isEnabledFor(logging.DEBUG):
            # Raw values as hex, to decode unknown fields from a debug log
            _LOGGER.debug("Status %s", {dp: _hex_or_raw(value) for dp, value in dps.items()})
        self._merge(dps)
        self.async_set_updated_data(self.data)

    @callback
    def _handle_disconnect(self) -> None:
        self.hass.async_create_task(self.async_request_refresh())
