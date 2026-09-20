"""Constants for the ON (Orka náttúrunnar) integration."""

DOMAIN = "on_is"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_BACKEND = "backend"
CONF_CHARGE_POINT_ID = "charge_point_id"
CONF_TEAM_ID = "team_id"
CONF_CONNECTOR_ID = "connector_id"
CONF_DEVICE_UUID = "device_uuid"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ACCESS_TOKEN_EXPIRES_AT = "access_token_expires_at"
CONF_REFRESH_TOKEN_EXPIRES_AT = "refresh_token_expires_at"

# Internal config key for the integer ID
CONF_LOCATION_ID = "location_id" 
# Field name for the User Input (QR Code)
CONF_EVSE_CODE = "evse_code"

BACKEND_OCEAN = "ocean"
BACKEND_MONTA_APP = "monta_app"
DEFAULT_BACKEND = BACKEND_MONTA_APP

SCAN_INTERVAL_SECONDS = 30
