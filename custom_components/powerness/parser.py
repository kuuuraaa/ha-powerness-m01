"""Decoders for the raw data points of the Powerness M01 / EPP BES battery.

The device reports most of its values as base64 encoded binary blobs. Two
layouts are used:

* ``battery_dc_data`` (DP 10): a version byte followed by fixed 29 byte
  records. The first record (serial ``000…``) is the whole stack, every
  following record is one battery pack.
* ``bms_message`` / ``stack_info`` / ``bcu_info_hex`` / ``alarm_message``:
  a two byte header, optionally a 22 character serial number, followed by
  TLV entries (tag, length, big endian value).
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field

SERIAL_LEN = 22
DC_RECORD_LEN = SERIAL_LEN + 7


@dataclass(frozen=True, slots=True)
class DcRecord:
    """One record of the heartbeat data (stack or single pack)."""

    serial: str
    soc: int
    voltage: float
    current: float
    # Not decoded yet, signed: 0 while idle, +3 while charging, -1 while
    # discharging
    raw_tail: int

    @property
    def power(self) -> float:
        """Battery power in W, positive while charging."""
        return round(self.voltage * self.current, 1)


@dataclass(frozen=True, slots=True)
class TlvMessage:
    """A decoded TLV message."""

    serial: str | None
    values: dict[int, int] = field(default_factory=dict)


def decode_b64(value: object) -> bytes | None:
    """Decode a base64 DP value, return None for anything unusable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None


def _signed16(raw: int) -> int:
    return raw - 0x10000 if raw & 0x8000 else raw


def _serial(data: bytes) -> str:
    return data.decode("ascii", errors="replace")


def parse_dc_data(value: object) -> list[DcRecord]:
    """Parse ``battery_dc_data`` into stack and pack records."""
    data = decode_b64(value)
    if not data or len(data) < 1 + DC_RECORD_LEN:
        return []
    records = []
    for offset in range(1, len(data) - DC_RECORD_LEN + 1, DC_RECORD_LEN):
        rec = data[offset : offset + DC_RECORD_LEN]
        records.append(
            DcRecord(
                serial=_serial(rec[:SERIAL_LEN]),
                soc=rec[22],
                voltage=int.from_bytes(rec[23:25]) / 10,
                current=_signed16(int.from_bytes(rec[25:27])) / 10,
                raw_tail=_signed16(int.from_bytes(rec[27:29])),
            )
        )
    return records


def parse_tlv(value: object) -> TlvMessage | None:
    """Parse a TLV style message (``bms_message``, ``stack_info``, …)."""
    data = decode_b64(value)
    if not data or len(data) < 2:
        return None
    pos = 2
    serial = None
    # Messages for a single pack carry its serial right after the header
    if len(data) >= 2 + SERIAL_LEN and data[2 : 2 + SERIAL_LEN].isalnum():
        serial = _serial(data[2 : 2 + SERIAL_LEN])
        pos += SERIAL_LEN
    values: dict[int, int] = {}
    while pos + 2 <= len(data):
        tag, length = data[pos], data[pos + 1]
        chunk = data[pos + 2 : pos + 2 + length]
        if len(chunk) != length:
            break
        values[tag] = int.from_bytes(chunk)
        pos += 2 + length
    return TlvMessage(serial=serial, values=values)


# Known TLV tags. Energy counters are in 0.1 kWh; two snapshots a few weeks
# apart moved by +31.3 kWh charged / +28.7 kWh discharged / +30.4 kWh PV.
BMS_SOC = 0x03
BMS_VOLTAGE = 0x08
BMS_CURRENT = 0x0A
# Change in opposite directions (7/8 at 50 %, 15/0 at 0 %), most likely the
# index of the highest / lowest cell of the 16S pack
BMS_CELL_A = 0x23
BMS_CELL_B = 0x24
BMS_ENERGY_CHARGED = 0x25
BMS_ENERGY_DISCHARGED = 0x26
STACK_SOC = 0x0C
STACK_ENERGY_CHARGED = 0x0E
STACK_ENERGY_DISCHARGED = 0x0F
STACK_VOLTAGE = 0x12
STACK_CURRENT = 0x13
# bcu_info_hex: 0x07 is the battery state the app shows: 0 while charging
# (+5.8 A), 1 while discharging (-3.6 A), 2 = "Standby" in the app
BCU_STATE = 0x07
BCU_STATES = {0: "charging", 1: "discharging", 2: "standby"}


def tlv_signed16(msg: TlvMessage, tag: int) -> int | None:
    """Return a TLV value interpreted as signed 16 bit."""
    raw = msg.values.get(tag)
    return None if raw is None else _signed16(raw)


@dataclass(frozen=True, slots=True)
class SchedulePeriod:
    """One period of ``time_schedule`` (DP 103)."""

    start: str
    end: str
    flags: tuple[int, int]

    @property
    def charge(self) -> bool:
        """Charging is allowed in this period."""
        return bool(self.flags[0])

    @property
    def discharge(self) -> bool:
        """Discharging is allowed in this period."""
        return bool(self.flags[1])

    def contains(self, hhmm: str) -> bool:
        """Return True if the time ``HH:MM`` falls into this period."""
        if self.start <= self.end:
            return self.start <= hhmm < self.end
        return hhmm >= self.start or hhmm < self.end


def parse_schedule(value: object) -> list[SchedulePeriod]:
    """Parse ``time_schedule``: 6 bytes per period.

    start hour, start minute, end hour, end minute, charge allowed,
    discharge allowed. The number of periods follows what is set in the app
    (``0f 00 17 00 01 00 00 00 09 00 00 01`` = charge 15:00-23:00,
    discharge 00:00-09:00).
    """
    data = decode_b64(value)
    if not data:
        return []
    periods = []
    for pos in range(0, len(data) - 5, 6):
        sh, sm, eh, em, a, b = data[pos : pos + 6]
        if sh > 23 or eh > 23 or sm > 59 or em > 59:
            return []
        periods.append(SchedulePeriod(f"{sh:02d}:{sm:02d}", f"{eh:02d}:{em:02d}", (a, b)))
    return periods


CHARGE_FLAGS = (1, 0)
DISCHARGE_FLAGS = (0, 1)
# The app offers up to four periods, each either charging or discharging
MAX_PERIODS = 4

MODE_OFF = "off"
MODE_FLAGS = {
    "charge": CHARGE_FLAGS,
    "discharge": DISCHARGE_FLAGS,
    # Older app versions also wrote periods that allow both
    "charge_discharge": (1, 1),
}
SLOT_MODES = [MODE_OFF, *MODE_FLAGS]


def mode_of(flags: tuple[int, int]) -> str:
    """Return the slot mode for a period's flags."""
    normalized = (int(bool(flags[0])), int(bool(flags[1])))
    return next((mode for mode, f in MODE_FLAGS.items() if f == normalized), MODE_OFF)


def encode_schedule(periods: list[SchedulePeriod]) -> str:
    """Encode periods into the DP 103 format (inverse of ``parse_schedule``)."""
    if not periods or len(periods) > MAX_PERIODS:
        raise ValueError(f"A schedule needs 1 to {MAX_PERIODS} periods")
    out = bytearray()
    for period in periods:
        sh, sm = (int(part) for part in period.start.split(":"))
        eh, em = (int(part) for part in period.end.split(":"))
        out += bytes([sh, sm, eh, em, int(period.charge), int(period.discharge)])
    return base64.b64encode(bytes(out)).decode()


@dataclass(frozen=True, slots=True)
class ScheduleSlot:
    """One of the four editable periods; ``off`` slots keep their times."""

    start: str = "00:00"
    end: str = "00:00"
    mode: str = MODE_OFF

    @property
    def period(self) -> SchedulePeriod | None:
        """The period written to the device, None while off."""
        if self.mode == MODE_OFF:
            return None
        return SchedulePeriod(self.start, self.end, MODE_FLAGS[self.mode])


def active_periods(slots: list[ScheduleSlot]) -> list[SchedulePeriod]:
    """Periods of all slots that are not off, in slot order."""
    return [period for slot in slots if (period := slot.period) is not None]


def sync_slots(slots: list[ScheduleSlot], periods: list[SchedulePeriod]) -> list[ScheduleSlot]:
    """Bring the slots in line with the schedule read from the device.

    Unchanged when the slots already describe that schedule (e.g. we wrote
    it). Otherwise (changed in the app) the device periods fill the first
    slots and the remaining slots are switched off, keeping their times.
    """
    if active_periods(slots) == [p for p in periods if mode_of(p.flags) != MODE_OFF]:
        return slots
    new = [ScheduleSlot(p.start, p.end, mode_of(p.flags)) for p in periods[:MAX_PERIODS]]
    old = list(slots) + [ScheduleSlot()] * MAX_PERIODS
    rest = [ScheduleSlot(s.start, s.end) for s in old[len(new) : MAX_PERIODS]]
    return new + rest
