"""Raw value mappings for supported Panasonic fresh-air devices."""

from __future__ import annotations

import math

from homeassistant.components.sensor import SensorDeviceClass

RUN_MODE_READ_MAP: dict[int, str] = {
    # Observed on Aircle-13-03 / FV-35ZDP2C with the China mobile app.
    1: "热交换",
    4: "内循环",
    6: "自动ECO",
    7: "消毒",
    # Keep legacy/alternate codes as read-only fallbacks.
    48: "热交换",
    51: "内循环",
    53: "自动ECO",
}

RUN_MODE_SET_MAP: dict[str, int] = {
    label: raw for raw, label in RUN_MODE_READ_MAP.items() if raw < 48
}

AIR_VOLUME_MAP: dict[int, str] = {
    0: "低噪音",
    1: "弱",
    2: "强",
}

PRESSURE_MODE_MAP: dict[int, str] = {
    0: "标准模式",
    1: "正压模式",
    2: "自定义模式",
}

PM25_THRESHOLD_MAP: dict[int, str] = {
    0: "35 µg/m³",
    1: "50 µg/m³",
    2: "75 µg/m³",
}

TVOC_THRESHOLD_MAP: dict[int, str] = {
    0: "低",
    1: "高",
}

OUTER_FILTER_CYCLE_MAP: dict[int, str] = {
    0: "90天",
    1: "120天",
    2: "150天",
    3: "180天",
}

EXHAUST_STRENGTH_MAP: dict[int, str] = {
    0: "0%",
    20: "20%",
    40: "40%",
    60: "60%",
    80: "80%",
}

PRESSURE_MODE_SET_MAP: dict[str, int] = {
    label: raw for raw, label in PRESSURE_MODE_MAP.items()
}

PM25_THRESHOLD_SET_MAP: dict[str, int] = {
    label: raw for raw, label in PM25_THRESHOLD_MAP.items()
}

EXHAUST_STRENGTH_SET_MAP: dict[str, int] = {
    label: raw for raw, label in EXHAUST_STRENGTH_MAP.items()
}

INVALID_BY_SENSOR_CLASS: dict[SensorDeviceClass | None, tuple[int, ...]] = {
    SensorDeviceClass.PM25: (65535, 255, -1),
    SensorDeviceClass.HUMIDITY: (255, -1),
    SensorDeviceClass.TEMPERATURE: (127, 255, -127, -128),
    SensorDeviceClass.CO2: (65535, 255, -1),
}

INVALID_BY_KEY: dict[str, tuple[int, ...]] = {
    "filterTimeLeft": (255, -1),
    "pm25Quti": (65535, -1),
    "raTVC": (255,),
    "oaFilExTL": (65535,),
    "saFilExTL": (65535,),
    "raFilExTL": (65535,),
}

PHYSICAL_RANGE: dict[SensorDeviceClass, tuple[float, float]] = {
    SensorDeviceClass.HUMIDITY: (0, 100),
    SensorDeviceClass.TEMPERATURE: (-50, 80),
    SensorDeviceClass.PM25: (0, 1000),
    SensorDeviceClass.CO2: (0, 10000),
}


def int_or_none(value) -> int | None:
    """Return an int when the raw cloud value is integer-like."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def mapped_option(raw, mapping: dict[int, str]) -> str | None:
    """Map a raw select value to a HA option label."""
    int_value = int_or_none(raw)
    if int_value is None or int_value in (255, 65535, -1):
        return None
    return mapping.get(int_value)


def clean_sensor_value(raw, key: str, device_class: SensorDeviceClass | None):
    """Normalize cloud raw values into valid Home Assistant sensor values."""
    if raw is None or raw == "":
        return None
    try:
        value: int | float = int(raw)
    except TypeError, ValueError:
        try:
            value = float(raw)
        except TypeError, ValueError:
            return None

    sentinels = INVALID_BY_KEY.get(key) or INVALID_BY_SENSOR_CLASS.get(device_class, ())
    if value in sentinels:
        return None

    value_range = PHYSICAL_RANGE.get(device_class)
    if value_range is not None and not value_range[0] <= value <= value_range[1]:
        return None

    return value


def hours_to_days(raw, key: str = "") -> int | None:
    """Convert cloud lifetime hours to app-style remaining days."""
    hours = clean_sensor_value(raw, key, None)
    if hours is None:
        return None
    if hours < 0 or hours == 65535:
        return None
    return math.ceil(hours / 24)
