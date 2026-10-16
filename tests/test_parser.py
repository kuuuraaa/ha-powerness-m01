"""Tests for the payload decoders."""

import pytest

from custom_components.powerness import parser, sensor
from custom_components.powerness.coordinator import PowernessData

from .const import (
    ALARM_MESSAGE,
    BCU_INFO_CHARGING,
    BCU_INFO_DISCHARGING,
    BCU_INFO_HALF,
    BMS_MESSAGE,
    BMS_MESSAGE_HALF,
    DC_DATA_CHARGING,
    DC_DATA_CHARGING_REAL,
    DC_DATA_DISCHARGING,
    DC_DATA_DISCHARGING_REAL,
    DC_DATA_IDLE,
    SERIAL,
    STACK_INFO,
    STACK_INFO_HALF,
    STATUS_DPS,
    TIME_SCHEDULE_APP,
    TIME_SCHEDULE_FOUR,
    TIME_SCHEDULE_HALF,
)


def test_dc_data_idle() -> None:
    """The recorded idle heartbeat matches the user's template sensors."""
    stack, pack = parser.parse_dc_data(DC_DATA_IDLE)
    assert stack.serial == "0" * 22
    assert pack.serial == SERIAL
    assert (stack.soc, stack.voltage, stack.current) == (0, 51.1, 0.0)


def test_dc_data_signed_current() -> None:
    """Negative current means discharging."""
    stack = parser.parse_dc_data(DC_DATA_DISCHARGING)[0]
    assert (stack.soc, stack.voltage, stack.current) == (80, 53.0, -4.2)
    assert stack.power == -222.6
    assert parser.parse_dc_data(DC_DATA_CHARGING)[0].power == 313.8


def test_bms_tlv() -> None:
    """bms_message holds SOC, voltage and current as TLV entries."""
    msg = parser.parse_tlv(BMS_MESSAGE)
    assert msg.serial == SERIAL
    assert msg.values[parser.BMS_SOC] == 0
    assert msg.values[parser.BMS_VOLTAGE] == 511
    assert msg.values[parser.BMS_ENERGY_CHARGED] == 2180
    assert msg.values[parser.BMS_ENERGY_DISCHARGED] == 2032


def test_stack_info_without_serial() -> None:
    """stack_info has no serial number."""
    msg = parser.parse_tlv(STACK_INFO)
    assert msg.serial is None
    assert msg.values == {0x0C: 0, 0x0E: 2180, 0x0F: 2032, 0x12: 511, 0x13: 0}


def test_alarms_all_clear() -> None:
    """The recorded alarm message has every flag cleared."""
    msg = parser.parse_tlv(ALARM_MESSAGE)
    assert len(msg.values) == 9
    assert not any(msg.values.values())


def test_garbage() -> None:
    """Invalid values never raise."""
    for value in (None, "", 5, "not base64!", "AAAA"):
        assert parser.parse_dc_data(value) == []
    assert parser.parse_tlv(None) is None
    assert parser.parse_tlv("AQ==") is None


def test_data_model() -> None:
    """Derived values like the template helpers computed them."""
    data = PowernessData(dps={**STATUS_DPS, "10": DC_DATA_CHARGING, "108": 55})
    assert data.soc == 57
    assert data.power == 313.8
    assert data.pv_current == 5.5
    assert data.pv_power == pytest.approx(287.6, abs=0.1)
    assert data.pv_total == 331.2
    assert data.temperature == 18
    assert data.lifetime_charged == 218.0
    assert data.lifetime_discharged == 203.2


def test_data_model_falls_back_to_bms() -> None:
    """Without a heartbeat the BMS message still gives SOC and voltage."""
    data = PowernessData(dps={"4": BMS_MESSAGE})
    assert data.soc == 0
    assert data.voltage == 51.1
    assert data.current == 0.0


def test_half_snapshot() -> None:
    """The 50 % snapshot: stack SOC tag, signed BMS current, counters."""
    data = PowernessData(dps={"2": STACK_INFO_HALF, "4": BMS_MESSAGE_HALF, "8": BCU_INFO_HALF})
    assert data.soc == 50
    assert data.voltage == 52.4
    assert data.current == -0.1
    assert data.lifetime_charged == 186.7
    assert data.lifetime_discharged == 174.5
    assert data.bcu.values[parser.BCU_STATE] == 1
    assert (data.bms.values[parser.BMS_CELL_A], data.bms.values[parser.BMS_CELL_B]) == (7, 8)


def test_schedule() -> None:
    """Three periods with two flags each, the last one wraps past midnight."""
    periods = parser.parse_schedule(TIME_SCHEDULE_HALF)
    assert [(p.start, p.end, p.flags) for p in periods] == [
        ("09:00", "15:30", (1, 0)),
        ("15:30", "23:59", (0, 1)),
        ("00:00", "09:00", (1, 1)),
    ]
    assert periods[0].contains("12:00")
    assert not periods[0].contains("15:30")
    assert parser.SchedulePeriod("22:00", "06:00", (0, 0)).contains("01:00")
    assert parser.parse_schedule("AAAB") == []


def test_schedule_flags_from_app() -> None:
    """Flag 1 is charging, flag 2 is discharging, as set in the app."""
    charge, discharge = parser.parse_schedule(TIME_SCHEDULE_APP)
    assert (charge.start, charge.end, charge.charge, charge.discharge) == (
        "15:00",
        "23:00",
        True,
        False,
    )
    assert (discharge.start, discharge.end, discharge.charge, discharge.discharge) == (
        "00:00",
        "09:00",
        False,
        True,
    )


def test_no_negative_zero() -> None:
    """Idle power is shown as 0 W, never as -0 W."""
    assert str(sensor._negative(-0.0)) == "0.0"
    assert str(sensor._negative(0.0)) == "0.0"
    assert str(sensor._positive(-0.0)) == "0.0"
    assert sensor._negative(-222.6) == 222.6


def test_encode_schedule_roundtrip() -> None:
    """Encoding gives back exactly what the app wrote."""
    periods = parser.parse_schedule(TIME_SCHEDULE_APP)
    assert parser.encode_schedule(periods) == TIME_SCHEDULE_APP
    assert parser.encode_schedule(parser.parse_schedule(TIME_SCHEDULE_HALF)) == TIME_SCHEDULE_HALF
    with pytest.raises(ValueError):
        parser.encode_schedule([])


def test_four_periods_from_app() -> None:
    """Four periods in the order the app stores them."""
    periods = parser.parse_schedule(TIME_SCHEDULE_FOUR)
    assert [(p.start, p.end, parser.mode_of(p.flags)) for p in periods] == [
        ("05:00", "06:00", "discharge"),
        ("04:00", "05:00", "charge"),
        ("01:00", "02:00", "charge"),
        ("02:00", "03:00", "discharge"),
    ]
    assert parser.encode_schedule(periods) == TIME_SCHEDULE_FOUR
    with pytest.raises(ValueError):
        parser.encode_schedule(periods + periods[:1])


def test_sync_slots() -> None:
    """Slots follow the device, but keep their layout for our own writes."""
    empty = [parser.ScheduleSlot()] * 4
    slots = parser.sync_slots(empty, parser.parse_schedule(TIME_SCHEDULE_APP))
    assert slots == [
        parser.ScheduleSlot("15:00", "23:00", "charge"),
        parser.ScheduleSlot("00:00", "09:00", "discharge"),
        parser.ScheduleSlot(),
        parser.ScheduleSlot(),
    ]
    # Slot 1 switched off in HA: the device gets only slot 2, slots stay put
    ours = [parser.ScheduleSlot("15:00", "23:00", "off"), *slots[1:]]
    written = parser.active_periods(ours)
    assert written == [parser.SchedulePeriod("00:00", "09:00", (0, 1))]
    assert parser.sync_slots(ours, written) is ours

    # Changed in the app: device periods fill the first slots, times of the
    # others are kept but switched off
    four = parser.sync_slots(ours, parser.parse_schedule(TIME_SCHEDULE_FOUR))
    assert [s.mode for s in four] == ["discharge", "charge", "charge", "discharge"]
    two = parser.sync_slots(four, parser.parse_schedule(TIME_SCHEDULE_APP))
    assert two[2] == parser.ScheduleSlot("01:00", "02:00", "off")


def test_charging_snapshot() -> None:
    """Real charging data: state code 0, positive current."""
    data = PowernessData(dps={"10": DC_DATA_CHARGING_REAL, "8": BCU_INFO_CHARGING, "108": 67})
    assert (data.soc, data.voltage, data.current) == (2, 52.1, 5.8)
    assert data.power == 302.2
    assert parser.BCU_STATES[data.bcu_state] == "charging"
    assert data.stack.raw_tail == 3
    assert parser.BCU_STATES[parser.parse_tlv(BCU_INFO_HALF).values[parser.BCU_STATE]] == (
        "discharging"
    )


def test_discharging_snapshot() -> None:
    """Real discharging data: state code 1, negative current and tail."""
    data = PowernessData(dps={"10": DC_DATA_DISCHARGING_REAL, "8": BCU_INFO_DISCHARGING})
    assert (data.soc, data.voltage, data.current) == (28, 52.6, -3.6)
    assert data.power == -189.4
    assert sensor._negative(data.power) == 189.4
    assert parser.BCU_STATES[data.bcu_state] == "discharging"
    assert data.stack.raw_tail == -1
