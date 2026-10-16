"""Constants for the Powerness M01 / EPP BES integration."""

from homeassistant.const import Platform

DOMAIN = "powerness"
PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_PROTOCOL_VERSION = "protocol_version"
CONF_PRODUCT_ID = "product_id"
CONF_USER_CODE = "user_code"
CONF_KEEP_ALIVE = "keep_alive"

PROTOCOL_VERSIONS = ["3.4", "3.3"]
DEFAULT_PROTOCOL_VERSION = "3.4"

# Same public client the Home Assistant core Tuya integration uses for the
# Smart Life QR code login
TUYA_CLIENT_ID = "HA_3y9q4ak7g4ephrvke"
TUYA_SCHEMA = "haauthorize"

TUYA_CATEGORY = "cnsb"
KNOWN_PRODUCT_IDS = {"mwllseqnhzar191l"}

# Data points
DP_GET_TERMINAL_DATA = "1"
DP_STACK_INFO = "2"
DP_BMS_MESSAGE = "4"
DP_BCU_INFO = "8"
DP_ALARM_MESSAGE = "9"
DP_BATTERY_DC_DATA = "10"
DP_DEVICE_SN = "14"
DP_CHARGER_SWITCH = "101"
DP_DISCHARGE_SWITCH = "102"
DP_TIME_SCHEDULE = "103"
DP_TEMPERATURE = "104"
DP_FIRMWARE = "105"
DP_STATUS_PV = "106"
DP_PV_TOTAL = "107"
DP_PV_CURRENT = "108"

# Not part of the full query answer, only reported on change. Requested
# explicitly and remembered across restarts.
PERSISTED_DPS = (DP_CHARGER_SWITCH, DP_DISCHARGE_SWITCH, DP_TIME_SCHEDULE)

# Writing this to DP 1 makes the device stream live data, like the app does
WAKE_PAYLOAD = "AQEBAQE="

# Live data counts as stale after this many seconds without a heartbeat
STALE_AFTER = 30
KEEP_ALIVE_CHECK = 10
POLL_INTERVAL = 60
