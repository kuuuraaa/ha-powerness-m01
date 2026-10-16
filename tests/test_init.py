"""End-to-end setup against the fake battery."""

import asyncio
from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.powerness import parser
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DC_DATA_CHARGING, DEVICE_ID, TIME_SCHEDULE_APP, TIME_SCHEDULE_FOUR
from .fake_device import FakeBattery

ENTITY = "sensor.balkonkraftwerk_batterie"


async def _wait_for(check) -> None:
    """Give the real socket round trip to the fake battery some time."""
    for _ in range(100):
        if check():
            return
        await asyncio.sleep(0.01)
    assert check()


@pytest.mark.usefixtures("no_discovery")
async def test_setup_and_wake(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_battery: FakeBattery,
) -> None:
    """Setup wakes the battery, pushed live data lands in the sensors."""
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    # The wake command is sent on connect, the battery answers with live data
    assert fake_battery.received[0] == {"1": "AQEBAQE="}
    for _ in range(3):
        await hass.async_block_till_done()
    assert fake_battery.dps["10"] == DC_DATA_CHARGING

    assert hass.states.get(f"{ENTITY}_state_of_charge").state == "57"
    assert hass.states.get(f"{ENTITY}_voltage").state == "52.3"
    assert hass.states.get(f"{ENTITY}_charge_power").state == "313.8"
    assert hass.states.get(f"{ENTITY}_discharge_power").state == "0.0"
    assert hass.states.get(f"{ENTITY}_temperature").state == "18"
    assert hass.states.get(f"{ENTITY}_pv_energy_device_total").state == "331.2"
    assert hass.states.get("binary_sensor.balkonkraftwerk_batterie_alarm").state == STATE_OFF
    state = hass.states.get(f"{ENTITY}_battery_state")
    assert state.state == "standby"
    assert state.attributes["code"] == 2
    assert state.attributes["cell_index_a"] == 15
    schedule = hass.states.get(f"{ENTITY}_time_schedule")
    # Both permanent switches are on in the recorded data
    assert schedule.state == "permanent"
    assert schedule.attributes["periods"][0] == {
        "start": "09:00",
        "end": "15:30",
        "charge": False,
        "discharge": False,
    }
    assert hass.states.get(f"{ENTITY}_battery_power") is None

    # Stale data triggers another wake request
    coordinator = config_entry.runtime_data
    await coordinator._async_keep_alive(dt_util.utcnow() + timedelta(seconds=10))
    assert fake_battery.received.count({"1": "AQEBAQE="}) == 1
    await coordinator._async_keep_alive(dt_util.utcnow() + timedelta(seconds=45))
    await _wait_for(lambda: fake_battery.received.count({"1": "AQEBAQE="}) == 2)

    await hass.services.async_call(
        "switch",
        "turn_off",
        {ATTR_ENTITY_ID: "switch.balkonkraftwerk_batterie_charge_permanently"},
        blocking=True,
    )
    assert {"101": False} in fake_battery.received
    assert hass.states.get("switch.balkonkraftwerk_batterie_charge_permanently").state == STATE_OFF
    assert hass.states.get(f"{ENTITY}_time_schedule").state == "permanent"
    await hass.services.async_call(
        "switch",
        "turn_off",
        {ATTR_ENTITY_ID: "switch.balkonkraftwerk_batterie_discharge_permanently"},
        blocking=True,
    )
    # With both switches off the schedule applies (all periods off here)
    assert hass.states.get(f"{ENTITY}_time_schedule").state == "off"

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.usefixtures("no_discovery")
async def test_setup_unreachable(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """An unreachable battery makes the entry retry."""
    config_entry.add_to_hass(hass)
    # Nothing listens on 6668 on localhost
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("no_discovery")
async def test_old_entities_removed(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_battery: FakeBattery
) -> None:
    """Entities dropped in later versions are removed from the registry."""
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor", "powerness", f"{DEVICE_ID}_battery_power", config_entry=config_entry
    )
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(old.entity_id) is None


@pytest.mark.usefixtures("no_discovery")
async def test_schedule_editing(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_battery: FakeBattery
) -> None:
    """Slot entities and the action write the schedule like the app does."""
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _wait_for(lambda: "103" in config_entry.runtime_data.data.dps)
    slot = "balkonkraftwerk_batterie_period_{}_{}"

    async def set_time(n: int, part: str, value: str) -> None:
        await hass.services.async_call(
            "time",
            "set_value",
            {ATTR_ENTITY_ID: "time." + slot.format(n, part), "time": value},
            blocking=True,
        )

    async def set_mode(n: int, mode: str) -> None:
        await hass.services.async_call(
            "select",
            "select_option",
            {ATTR_ENTITY_ID: "select." + slot.format(n, "mode"), "option": mode},
            blocking=True,
        )

    # The recorded schedule only has periods that do nothing: all slots off
    assert hass.states.get("select." + slot.format(1, "mode")).state == "off"
    writes = len(fake_battery.received)
    # Times of a slot that is off are only remembered
    await set_time(1, "from", "15:00")
    await set_time(1, "until", "23:00")
    assert len(fake_battery.received) == writes
    assert hass.states.get("time." + slot.format(1, "from")).state == "15:00:00"
    await set_mode(1, "charge")
    await set_time(2, "until", "09:00")
    await set_mode(2, "discharge")
    # Byte for byte what the app wrote for the same schedule
    assert fake_battery.received[-1] == {"103": TIME_SCHEDULE_APP}

    # Switching slot 1 off keeps slot 2 where it is
    await set_mode(1, "off")
    assert fake_battery.received[-1] == {"103": "AAAJAAAB"}
    assert hass.states.get("select." + slot.format(2, "mode")).state == "discharge"
    with pytest.raises(HomeAssistantError):
        await set_mode(2, "off")

    await hass.services.async_call(
        "powerness",
        "set_schedule",
        {
            "config_entry_id": config_entry.entry_id,
            "periods": [
                {"start": "05:00", "end": "06:00", "mode": "discharge"},
                {"start": "04:00", "end": "05:00", "mode": "charge"},
                {"start": "01:00", "end": "02:00", "mode": "charge"},
                {"start": "02:00", "end": "03:00", "mode": "discharge"},
            ],
        },
        blocking=True,
    )
    assert fake_battery.received[-1] == {"103": TIME_SCHEDULE_FOUR}
    assert hass.states.get("select." + slot.format(4, "mode")).state == "discharge"
    assert hass.states.get("time." + slot.format(3, "from")).state == "01:00:00"

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            "powerness",
            "set_schedule",
            {"config_entry_id": config_entry.entry_id, "periods": []},
            blocking=True,
        )


@pytest.mark.usefixtures("no_discovery")
async def test_schedule_requested_and_remembered(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_battery: FakeBattery,
    hass_storage: dict,
) -> None:
    """The schedule left out of the query is requested and stored."""
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert {"updatedps": [103]} in fake_battery.received
    await _wait_for(lambda: "103" in config_entry.runtime_data.data.dps)

    # Flush the delayed save
    await config_entry.runtime_data.store.async_save(config_entry.runtime_data._stored_data())
    key = f"powerness.{config_entry.entry_id}"
    assert hass_storage[key]["data"]["dps"]["103"] == fake_battery.dps["103"]
    assert await hass.config_entries.async_unload(config_entry.entry_id)

    # Next start: the battery does not answer, the stored schedule is used
    fake_battery.answer_updatedps = False
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    periods = hass.states.get(f"{ENTITY}_time_schedule").attributes["periods"]
    assert periods[0]["start"] == "09:00"


@pytest.mark.usefixtures("no_discovery")
async def test_slots_without_known_schedule(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_battery: FakeBattery
) -> None:
    """Without any known schedule the slots start empty and still write."""
    fake_battery.answer_updatedps = False
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.balkonkraftwerk_batterie_period_3_mode", "option": "charge"},
        blocking=True,
    )
    assert parser.parse_schedule(fake_battery.dps["103"]) == [
        parser.SchedulePeriod("00:00", "00:00", (1, 0))
    ]
