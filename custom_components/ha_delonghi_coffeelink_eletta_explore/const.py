"""Constants for the De'Longhi Coffee Link – Eletta Explore integration."""

from __future__ import annotations

DOMAIN = "ha_delonghi_coffeelink_eletta_explore"
MANUFACTURER = "De'Longhi"

# Extracted from Coffee Link APK v4.9.6
APP_ID = "DLonghiCoffeeIdKit-sQ-id"
APP_SECRET = "DLonghiCoffeeIdKit-HT6b0VNd4y6CSha9ivM5k8navLw"
GIGYA_API_KEY = "3_e5qn7USZK-QtsIso1wCelqUKAK_IVEsYshRIssQ-X-k55haiZXmKWDHDRul2e5Y2"
GIGYA_BASE_URL = "https://accounts.eu1.gigya.com"
AYLA_EU_ADS_URL = "https://ads-eu.aylanetworks.com"
AYLA_EU_USER_URL = "https://user-field-eu.aylanetworks.com"
AYLA_EU_MDSS_URL = "https://mdss-field-eu.aylanetworks.com"
AYLA_EU_MSTREAM_URL = "https://mstream-field-eu.aylanetworks.com"

# Polling
DEFAULT_SCAN_INTERVAL = 30  # seconds
DSS_FALLBACK_SCAN_INTERVAL = 300  # full reconciliation while push is healthy
DEVICE_METADATA_REFRESH_INTERVAL = 600  # seconds
CONNECTION_INFO_REFRESH_INTERVAL = 3600  # seconds; diagnostic only
STATISTICS_SYNC_SETTLE_DELAY = 45  # bounded verification window; observed e8 responses can take 17-24 seconds
STATISTICS_PROPERTY_PREFIXES = (
    "d7",  # beverage, recipe-usage and per-beverage volume counters
    "d510_",  # grounds fill
    "d512_",  # descale usage
    "d513_",  # filter usage
    "d524_",  # descale alerts
    "d550_",  # calculated water usage
    "d552_",  # descales
    "d553_",  # total water
    "d554_",  # filters
    "d555_",  # filtered water
    "d558_",  # drinks since descale warning
    "d580_",  # service counters on Striker
)
STATISTICS_SYNC_STARTUP_DELAY = 30  # let the initial poll and DSS stream settle first
STATISTICS_SYNC_INTERVAL = 3600  # cooperative refresh; do not hold the mobile-app session continuously
STATISTICS_SYNC_RETRY_INTERVAL = 300  # retry a skipped/failed refresh without cloud-request churn
POST_COMMAND_REFRESH_DELAY = 8  # seconds

# Ayla Data Stream Service (DSS). Coffee Link 4.9.6 enables this service and
# subscribes to both datapoint changes and device acknowledgements. The
# integration treats it as an acceleration layer; polling always remains the
# authoritative fallback.
DSS_SUBSCRIPTION_NAME = "HOME_ASSISTANT_COFFEELINK"
DSS_SUBSCRIPTION_DESCRIPTION = "DATAPOINT"
DSS_SUBSCRIPTION_TYPES = "datapoint,datapointack"
DSS_STREAM_IDLE_TIMEOUT = 75  # official heartbeat interval is 30 seconds
DSS_RECONNECT_MIN_DELAY = 3
DSS_RECONNECT_MAX_DELAY = 60
# Coffee Link 4.9.6 bundles AylaProperty.DEFAULT_ACK_WAIT_TIME = 10. Keep the
# same acknowledgement window before falling back to cloud-state inference.
DSS_ACK_GRACE_PERIOD = 10

# Persistence of learned Eletta beverage frames (survives HA restarts).
RECIPE_STORE_VERSION = 1
RECIPE_STORE_SAVE_DELAY = 2  # seconds; debounce writes to disk

# Property names vary by model:
# - PrimaDonna Soul (DL-millcore): data_request / data_response / device_connected
# - Eletta Explore (DL-striker-cb): app_data_request / app_data_response / app_device_connected
# Listed in detection priority order.
COMMAND_PROPERTY_CANDIDATES = ["data_request", "app_data_request"]
RESPONSE_PROPERTY_CANDIDATES = ["data_response", "app_data_response"]
CONNECTED_PROPERTY_CANDIDATES = ["device_connected", "app_device_connected"]

# Fallback cloud client id until an ECAM frame has supplied the machine-specific
# 4-byte signature. Learned signatures replace this value for session registration.
INTEGRATION_CLOUD_APP_ID = 0xC0FFEE11

APP_ID_PROPERTY = "app_id"  # machine property: current session holder
CONNECT_REFRESH_INTERVAL = 240  # refresh before 4*60s (device timeout ~300s)
CONNECT_SETTLE_DELAY = 4  # sleep after POST connect before confirmation
CONNECT_CONFIRM_TIMEOUT = 30  # do not leave a HA action hanging for several minutes
CONNECT_CONFIRM_POLL_INTERVAL = 1  # seconds between app_id polls during confirm
COMMAND_CONFIRM_TIMEOUT = 20  # beverage cloud propagation can exceed ten seconds
POWER_COMMAND_CONFIRM_TIMEOUT = 30  # waking/sleeping is slower than beverage acknowledgement
COMMAND_CONFIRM_POLL_INTERVAL = 1

# Ayla HTTP resilience (502/503/504 gateway timeouts seen on ads-eu.aylanetworks.com).
CLOUD_HTTP_RETRY_COUNT = 2
CLOUD_HTTP_RETRY_BACKOFF = 1.5  # seconds; multiplied by attempt index
CLOUD_TRANSIENT_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})
CLOUD_HTTP_TIMEOUT = 20  # seconds per request
CLOUD_RETRY_AFTER_DEFAULT = 60  # seconds when a 429 response has no usable hint
CLOUD_RETRY_AFTER_MAX = 300  # never let an upstream header stall HA indefinitely

# Config
CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# CRC16 AUG-CCITT
CRC_POLY = 0x1021
CRC_INIT = 0x1D0F

# Command structure
CMD_PREFIX = 0x0D  # App -> machine
CMD_RESPONSE_PREFIX = 0xD0  # Machine -> app
CMD_LENGTH = 0x0D  # 13 bytes payload
CMD_FAMILY_BREW = bytes([0x83, 0xF0])  # Brew beverage command family

# Eletta Explore (oem_model=DL-striker-cb) beverage frames carry a variable
# length recipe block terminated by this 2-byte trailer, then the CRC. The Soul
# (DL-millcore) frame has no trailer (fixed 6-byte recipe). See command_builder.
ELETTA_RECIPE_TRAILER = bytes([0x01, 0x0A])
# oem_model prefix of the Eletta Explore family (app_data_request channel).
ELETTA_OEM_PREFIX = "DL-striker"

# Actions
ACTION_START = 0x01
ACTION_STOP = 0x02

# Power / Wake command family (0x84 0x0f)
CMD_FAMILY_POWER = bytes([0x84, 0x0F])
POWER_WAKE_PARAMS = bytes([0x02, 0x01])  # observed wake command payload
# Standby (power off) payload - reported on Eletta (issue #1) and validated
# live on the reference PrimaDonna Soul (machine powered off, 2026-06-07).
POWER_STANDBY_PARAMS = bytes([0x01, 0x01])
# Session refresh / deep-standby nudge (DlghIoT refresh(), params 03 02, CRC 5640).
POWER_SESSION_REFRESH_PARAMS = bytes([0x03, 0x02])

# Statistics request (0xe8 0xf0). Coffee Link sends this frame when it opens its
# statistics view: 0d 06 e8 f0 00 <crc16> 00 00 <timestamp> <session tail>.
# Only this frame makes Eletta firmware upload changed d5xx/d7xx counter
# properties (also from standby); the 03 02 session refresh only republishes
# d302 and leaves counters stale until the next app or Wi-Fi session.
CMD_FAMILY_STATISTICS = bytes([0xE8, 0xF0])
STATISTICS_REQUEST_PARAMS = bytes([0x00])

# Machine monitor (d302_monitor_machine) - operational state published by the
# machine. Status codes from the DlghIoT client (framagit.org/mattgk/dlghiot),
# contributed via PR #5.
MONITOR_PROPERTY_CANDIDATES = ("d302_monitor_machine", "d302_monitor")
MACHINE_STATUS = {
    0: "standby",
    1: "waking_up",
    2: "going_to_sleep",
    4: "descaling",
    5: "preparing_steam",
    6: "recovering",
    7: "ready",
    8: "rinsing",
    10: "preparing_milk",
    11: "dispensing_hot_water",
    12: "cleaning_milk",
    16: "preparing_chocolate",
    17: "preparing_milk_alt",
    29: "unknown",
}
MACHINE_STATUS_OPTIONS = tuple(dict.fromkeys((*MACHINE_STATUS.values(), "preparing_beverage")))
CONNECTION_STATUS_OPTIONS = ("online", "offline", "unknown")


def normalize_connection_status(value: object) -> str:
    """Return a stable Home Assistant enum key for an Ayla connection value."""
    normalized = str(value).strip().lower() if value is not None else ""
    return normalized if normalized in CONNECTION_STATUS_OPTIONS else "unknown"


# Default recipe params (from captured hot water command)
# Bytes: temp_flag, reserved, quantity_low, quantity_high?, recipe_type, ???
DEFAULT_RECIPE_PARAMS = bytes([0x0F, 0x00, 0xFA, 0x1B, 0x01, 0x06])

# Beverage definitions: (bev_id, key, display_name, icon)
BEVERAGES = [
    (0x01, "espresso", "Espresso", "mdi:coffee"),
    (0x02, "coffee", "Coffee", "mdi:coffee"),
    (0x03, "long_coffee", "Long Coffee", "mdi:coffee-outline"),
    (0x04, "double_espresso", "Double Espresso", "mdi:coffee"),
    (0x05, "doppio", "Doppio+", "mdi:coffee"),
    (0x06, "americano", "Americano", "mdi:coffee"),
    (0x07, "cappuccino", "Cappuccino", "mdi:coffee"),
    (0x08, "latte_macchiato", "Latte Macchiato", "mdi:coffee"),
    (0x09, "caffelatte", "Caffe Latte", "mdi:coffee"),
    (0x0A, "flat_white", "Flat White", "mdi:coffee"),
    (0x0B, "espresso_macchiato", "Espresso Macchiato", "mdi:coffee"),
    (0x0C, "hot_milk", "Hot Milk", "mdi:cup"),
    (0x0D, "cappuccino_doppio", "Cappuccino Doppio+", "mdi:coffee"),
    (0x0F, "cappuccino_reverse", "Cappuccino Reverse", "mdi:coffee"),
    (0x10, "hot_water", "Hot Water", "mdi:water"),
    (0x16, "tea", "Tea", "mdi:tea"),
    (0x17, "coffee_pot", "Coffee Pot", "mdi:coffee-maker"),
    (0x18, "cortado", "Cortado", "mdi:coffee"),
    (0x19, "long_black", "Long Black", "mdi:coffee"),
    (0x1A, "mug_to_go", "Mug to Go", "mdi:coffee-to-go"),
    (0x1B, "brew_over_ice", "Brew Over Ice", "mdi:coffee"),
]

# Eletta reports captured recipes in a model-specific ID range.  Keep this
# catalogue shared by the button platform and command diagnostics so the same
# friendly name is used everywhere.
ELETTA_LEARNED_BEVERAGES: dict[int, tuple[str, str, str]] = {
    120: ("cold_brew", "Cold Brew", "mdi:snowflake"),
    140: ("cold_brew_mug_to_go", "Cold Brew Mug to Go", "mdi:coffee-to-go"),
    141: (
        "cold_brew_latte_mug_to_go",
        "Cold Brew Latte Mug to Go",
        "mdi:coffee-to-go",
    ),
    142: (
        "cold_brew_cappuccino_mug_to_go",
        "Cold Brew Cappuccino Mug to Go",
        "mdi:coffee-to-go",
    ),
}

# Coffee Link's Statistics screen normalizes different raw property layouts to
# common user-facing totals.  The names below are deliberately semantic and
# retain the established entity unique IDs across supported model families.
COFFEE_LINK_AGGREGATE_SENSORS = {
    "striker": (
        ("total_beverages", "total_black_coffee_beverages"),
        ("total_milk_drinks", "total_milk_drinks"),
        ("total_cold_milk_drinks", "total_cold_milk_drinks"),
        ("total_mug_bev", "total_mug_bev"),
    ),
    "legacy": (
        ("total_beverages", "total_black_coffee_beverages"),
        ("total_milk_drinks", "total_milk_drinks"),
    ),
}

# Counter properties to expose as sensors:
#   (candidate_property_names, entity_key, display_name, icon)
# Property names differ between models; the first candidate present on the device
# wins (same approach as COMMAND_PROPERTY_CANDIDATES). A sensor whose property is
# absent on the device is not created (avoids permanently-"unknown" entities).
# The d700-d703 family is intentionally absent here: Coffee Link gives those
# fields model-dependent aggregate semantics, handled above rather than exposed
# as misleading raw counters.
COUNTER_SENSORS = [
    (["d704_tot_bev_espressi"], "total_espresso", "Total espresso", "mdi:coffee"),
    (["d705_tot_id1_espr"], "total_espresso_alt", "Total espresso", "mdi:coffee"),
    (["d706_tot_id2_coffee"], "total_coffee", "Total coffee", "mdi:coffee"),
    (["d707_tot_id3_long"], "total_long_coffee", "Total Long Coffee", "mdi:coffee"),
    (["d708_tot_id5_doppio_p"], "total_doppio", "Total Doppio+", "mdi:coffee"),
    (["d709_id6_americano"], "total_americano", "Total Americano", "mdi:coffee"),
    (["d710_tot_id7_capp"], "total_cappuccino", "Total Cappuccino", "mdi:coffee"),
    (["d711_id8_lattmacc"], "total_latte_macchiato", "Total Latte Macchiato", "mdi:coffee"),
    (["d712_id9_cafflatt"], "total_caffelatte", "Total Caffe Latte", "mdi:coffee"),
    (["d713_id10_flatwhite"], "total_flat_white", "Total Flat White", "mdi:coffee"),
    (["d714_id11_esprmacc"], "total_espresso_macchiato", "Total Espresso Macchiato", "mdi:coffee"),
    (["d715_id12_hotmilk"], "total_hot_milk", "Total hot milk", "mdi:cup"),
    (["d716_id13_cappdoppio_p"], "total_cappuccino_doppio", "Total Cappuccino Doppio+", "mdi:coffee"),
    (["d717_id15_caprev"], "total_cappuccino_reverse", "Total Cappuccino Reverse", "mdi:coffee"),
    (["d718_id16_hotwater"], "total_hot_water", "Total hot water", "mdi:water"),
    (["d719_id22_tea"], "total_tea", "Total tea", "mdi:tea"),
    (["d720_tot_id23_coffee_pot"], "total_coffee_pot", "Total Coffee Pot", "mdi:coffee-maker"),
    (["d730_tot_id27_brew_over_ice"], "total_brew_over_ice", "Total Brew Over Ice", "mdi:coffee"),
    (["d731_tot_mug_hot"], "total_mug_hot", "Total hot Mug to Go beverages", "mdi:coffee-to-go"),
    (["d732_tot_mug_cold"], "total_mug_cold", "Total cold Mug to Go beverages", "mdi:coffee-to-go"),
    (["d735_iced_bev"], "total_iced_bev", "Total iced beverages", "mdi:snowflake"),
    (["d736_mug_bev"], "total_mug_bev", "Total Mug to Go", "mdi:coffee-to-go"),
    (["d737_mug_iced_bev"], "total_mug_iced_bev", "Total iced Mug to Go beverages", "mdi:snowflake"),
    (["d738_cold_brew_bev"], "total_cold_brew_bev", "Total cold coffee beverages", "mdi:snowflake"),
    (["d510_ground_cnt_percentage"], "grounds_container_fill", "Grounds container fill", "mdi:delete-variant"),
    (["d513_percentage_usage_fltr"], "filter_usage", "Water filter usage", "mdi:filter-check"),
    (["d512_percentage_to_deca"], "descale_limit_usage", "Remaining until descale", "mdi:water-percent"),
    (["d552_cnt_calc_tot"], "total_descales", "Total descales", "mdi:water-pump"),
    (["d553_water_tot_qty"], "water_total_quantity", "Total water volume", "mdi:water"),
    (["d554_cnt_filter_tot"], "total_filters_used", "Total filters used", "mdi:filter"),
    (["d555_water_filter_qty"], "water_filter_quantity", "Water volume through installed filter", "mdi:water-check"),
    (["d825_descale_status"], "descale_status", "Descale status", "mdi:water-pump"),
    (["d556_water_hardness"], "water_hardness", "Water hardness", "mdi:water-percent"),
    (["d558_bev_cnt_desc_on"], "beverages_since_descale_warning", "Beverages since descale warning", "mdi:counter"),
    (["d524_ix_calcare_alm_qty"], "descale_alert_count", "Descale alert count", "mdi:alert-circle-outline"),
]

# Per-recipe and recipe-group counters remain available for advanced users, but
# are disabled for new entity registrations to keep the default device page
# focused on Coffee Link's semantic summaries. Existing registry choices are
# preserved by Home Assistant.
DETAILED_COUNTER_KEYS = {
    "total_espresso",
    "total_espresso_alt",
    "total_coffee",
    "total_long_coffee",
    "total_doppio",
    "total_americano",
    "total_cappuccino",
    "total_latte_macchiato",
    "total_caffelatte",
    "total_flat_white",
    "total_espresso_macchiato",
    "total_hot_milk",
    "total_cappuccino_doppio",
    "total_cappuccino_reverse",
    "total_hot_water",
    "total_coffee_pot",
    "total_brew_over_ice",
    "total_mug_hot",
    "total_mug_cold",
    "total_iced_bev",
    "total_mug_iced_bev",
    "total_cold_brew_bev",
    "total_over_ice_espresso",
    "total_cold_brew",
}

# Selected user-facing counters derived from JSON breakdowns. The parent
# d738_cold_brew_bev counter is a mixed group: recipe id 57 is Over Ice
# Espresso, while ids 120-142 are Cold Brew variants. Keeping explicit key
# lists prevents future, unrelated firmware fields from being included by
# accident.
BREAKDOWN_COUNTER_SENSORS = [
    (
        ["d738_cold_brew_bev"],
        "total_over_ice_espresso",
        "Total Over Ice Espresso",
        "mdi:snowflake",
        ("tot_id57_over_ice_espresso",),
    ),
    (
        ["d738_cold_brew_bev"],
        "total_cold_brew",
        "Total Cold Brew Beverages",
        "mdi:snowflake",
        (
            "tot_id120_cold_brew_coffee",
            "tot_id121_cold_brew_coffee_ess",
            "tot_id122_cold_brew_coffee_pot",
            "tot_id123_cold_brew_latte",
            "tot_id124_cold_brew_cappuccino",
            "tot_id140_cold_brew_mug",
            "tot_id141_cold_brew_latte_mug",
            "tot_id142_cold_brew_cappuccino_mug",
        ),
    ),
]

PLATFORMS = ["sensor", "binary_sensor", "button"]

# Service names
SERVICE_SEND_RAW_COMMAND = "send_raw_command"
SERVICE_START_BEVERAGE = "start_beverage"
SERVICE_STOP_BEVERAGE = "stop_beverage"
