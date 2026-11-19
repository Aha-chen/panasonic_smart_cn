"""Constants for Panasonic Smart CN."""

from __future__ import annotations

DOMAIN = "panasonic_smart_cn"

CONF_DEVICES = "devices"
CONF_DEVICE_NAME = "device_name"
CONF_DEVICE_MODEL = "device_model"
CONF_DEV_SUB_TYPE_ID = "dev_sub_type_id"
CONF_FAMILY_ID = "family_id"
CONF_REAL_FAMILY_ID = "real_family_id"
CONF_SESSION_ID = "session_id"
CONF_CLIENT_ID = "client_id"
CONF_AUTO_RELOGIN = "auto_relogin"
CONF_USER_ID = "user_id"
CONF_UPDATE_INTERVAL = "update_interval"

DEFAULT_UPDATE_INTERVAL = 60
DEFAULT_AUTO_RELOGIN = False
MIN_UPDATE_INTERVAL = 10
MAX_UPDATE_INTERVAL = 900

PLATFORMS = ["fan", "sensor", "select", "switch", "button", "light"]

AUTH_EXPIRED_CODES = {"3003", "3004", "4102"}

BASE_URL = "https://app.psmartcloud.com/App"
URL_GET_TOKEN = f"{BASE_URL}/UsrGetToken"
URL_LOGIN = f"{BASE_URL}/UsrLogin"
URL_GET_DEVICES = f"{BASE_URL}/UsrGetBindDevInfo"

FRESH_AIR_CATEGORIES = {"0800", "0850"}

ENTRY_SCHEMA_VERSION = 1
