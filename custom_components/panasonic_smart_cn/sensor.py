"""Sensor platform."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfDensity,
    UnitOfRatio,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .entity import PanasonicDeviceEntity
from .protocol.appliances import (
    BATH_MODES,
    PURIFIER_PXP,
    PURIFIER_VXR,
)
from .protocol.erv import LEGACY_AIRCLE, SMALLERV02_FILTER_FIELD_LABELS
from .protocol.mappings import (
    RUN_MODE_READ_MAP,
    clean_sensor_value,
    hours_to_days,
    int_or_none,
    mapped_option,
)

PM25_UNIT = UnitOfDensity.MICROGRAMS_PER_CUBIC_METER
CO2_UNIT = UnitOfRatio.PARTS_PER_MILLION


@dataclass(frozen=True)
class SensorSpec:
    key: str
    name: str
    unique_suffix: str
    device_class: SensorDeviceClass | None
    unit: str | None
    icon: str | None = None
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    value_kind: str = "raw"


SENSORS: tuple[SensorSpec, ...] = (
    SensorSpec("raPMC", "回风 PM2.5", "ra_pm25", SensorDeviceClass.PM25, PM25_UNIT),
    SensorSpec("oaPMC", "室外 PM2.5", "oa_pm25", SensorDeviceClass.PM25, PM25_UNIT),
    SensorSpec("saPMC", "送风 PM2.5", "sa_pm25", SensorDeviceClass.PM25, PM25_UNIT),
    SensorSpec("raCo2C", "回风 CO2", "ra_co2", SensorDeviceClass.CO2, CO2_UNIT),
    SensorSpec(
        "raTeC",
        "回风温度",
        "ra_temp",
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    ),
    SensorSpec(
        "oaTeC",
        "室外温度",
        "oa_temp",
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    ),
    SensorSpec(
        "saTeC",
        "送风温度",
        "sa_temp",
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    ),
    SensorSpec(
        "raHumC", "回风湿度", "ra_humidity", SensorDeviceClass.HUMIDITY, PERCENTAGE
    ),
    SensorSpec(
        "oaHumC", "室外湿度", "oa_humidity", SensorDeviceClass.HUMIDITY, PERCENTAGE
    ),
    SensorSpec(
        "oaFilClTL",
        "新风集尘过滤网清洁倒计时",
        "oa_clean_life",
        None,
        UnitOfTime.DAYS,
        "mdi:air-filter",
        None,
        "days",
    ),
    SensorSpec(
        "raFilClTL",
        "回风过滤网清洁倒计时",
        "ra_clean_life",
        None,
        UnitOfTime.DAYS,
        "mdi:air-filter",
        None,
        "days",
    ),
    SensorSpec(
        "resFilClTL",
        "初效过滤网清洁倒计时",
        "res_clean_life",
        None,
        UnitOfTime.DAYS,
        "mdi:air-filter",
        None,
        "days",
    ),
    SensorSpec(
        "resFilExTL",
        "初效过滤网更换倒计时",
        "res_filter_life",
        None,
        UnitOfTime.DAYS,
        "mdi:air-filter",
        None,
        "days",
    ),
    SensorSpec(
        "oaFilExTL",
        "新风集尘过滤网更换倒计时",
        "oa_filter_life",
        None,
        UnitOfTime.DAYS,
        "mdi:air-filter",
        None,
        "days",
    ),
    SensorSpec(
        "saFilExTL",
        "送风集尘过滤网更换倒计时",
        "sa_filter_life",
        None,
        UnitOfTime.DAYS,
        "mdi:air-filter",
        None,
        "days",
    ),
    SensorSpec(
        "raFilExTL",
        "回风过滤网更换倒计时",
        "ra_filter_life",
        None,
        UnitOfTime.DAYS,
        "mdi:air-filter",
        None,
        "days",
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensors."""
    coordinator = entry.runtime_data
    for device in coordinator.devices.values():
        _add_device_entities(coordinator, device, async_add_entities)


def _add_device_entities(coordinator, device, async_add_entities):
    profile = device.profile
    if profile in BATH_MODES:
        entities = [PanasonicBathroomTimer(coordinator, device)]
    elif profile in {PURIFIER_PXP, PURIFIER_VXR}:
        specs = [
            SensorSpec(
                "filterTimeLeft", "滤网剩余", "filter_remaining", None, PERCENTAGE
            ),
        ]
        if profile == PURIFIER_VXR:
            specs.extend(
                [
                    SensorSpec(
                        "humiCur",
                        "室内湿度",
                        "indoor_humidity",
                        SensorDeviceClass.HUMIDITY,
                        PERCENTAGE,
                    ),
                    SensorSpec(
                        "pm25Quti",
                        "室内 PM2.5",
                        "indoor_pm25",
                        SensorDeviceClass.PM25,
                        PM25_UNIT,
                    ),
                ]
            )
        entities = [
            PanasonicFreshAirSensor(coordinator, device, spec) for spec in specs
        ]
    elif profile == LEGACY_AIRCLE:
        entities = [
            PanasonicFreshAirSensor(coordinator, device, spec) for spec in SENSORS
        ]
        entities.append(PanasonicRunModeSensor(coordinator, device))
    else:
        reported = set((coordinator.data or {}).get(device.device_id, {}))
        supported = (device.erv.sensor_keys if device.erv else None) or reported
        specs = [spec for spec in SENSORS if spec.key in supported]
        if "raCO2C" in supported and "raCo2C" not in supported:
            specs.append(
                SensorSpec(
                    "raCO2C", "回风 CO₂", "ra_co2", SensorDeviceClass.CO2, CO2_UNIT
                )
            )
        for key, label in (
            SMALLERV02_FILTER_FIELD_LABELS
            if profile == "SMALLERV02"
            else {
                "pmFstFilClTL": "PM2.5 滤网清洁倒计时",
                "pmFstFilExTL": "PM2.5 滤网更换倒计时",
                "returnInFilExTL": "回风滤网更换倒计时",
            }
        ).items():
            if key in supported:
                specs.append(
                    SensorSpec(
                        key,
                        label,
                        key,
                        None,
                        UnitOfTime.DAYS,
                        "mdi:air-filter",
                        None,
                        "days",
                    )
                )
        entities = [
            PanasonicFreshAirSensor(coordinator, device, spec) for spec in specs
        ]
    entities.append(PanasonicRawStatusSensor(coordinator, device))
    entities.append(PanasonicProtocolSensor(coordinator, device))
    async_add_entities(entities)


class PanasonicFreshAirSensor(PanasonicDeviceEntity, SensorEntity):
    """Numeric fresh-air sensor."""

    def __init__(self, coordinator, device, spec: SensorSpec) -> None:
        super().__init__(coordinator, device)
        self._spec = spec
        self._attr_name = spec.name
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_{spec.unique_suffix}"
        if spec.device_class is not None:
            self._attr_device_class = spec.device_class
        if spec.unit is not None:
            self._attr_native_unit_of_measurement = spec.unit
        if spec.icon is not None:
            self._attr_icon = spec.icon
        if spec.state_class is not None:
            self._attr_state_class = spec.state_class

    @property
    def native_value(self):
        """Return cleaned sensor value."""
        if self._spec.value_kind == "days":
            return hours_to_days(self.raw_value(self._spec.key), self._spec.key)
        return clean_sensor_value(
            self.raw_value(self._spec.key),
            self._spec.key,
            self._spec.device_class,
        )

    @property
    def extra_state_attributes(self):
        """Expose raw value for protocol verification."""
        attrs = {"field": self._spec.key, "raw_value": self.raw_value(self._spec.key)}
        if self._spec.value_kind == "days":
            attrs["raw_hours"] = self.raw_value(self._spec.key)
        return attrs


class PanasonicRunModeSensor(PanasonicDeviceEntity, SensorEntity):
    """Read-only run mode until SET mapping is verified."""

    _attr_icon = "mdi:fan-auto"

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_name = "运行模式"
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_run_mode"

    @property
    def native_value(self):
        """Return mapped run mode."""
        if int_or_none(self.raw_value("holM")) == 1:
            return "度假模式"
        return mapped_option(self.raw_value("runM"), RUN_MODE_READ_MAP)

    @property
    def extra_state_attributes(self):
        """Expose raw value and mapping."""
        return {
            "field": "runM",
            "raw_value": self.raw_value("runM"),
            "holiday_raw_value": self.raw_value("holM"),
            "value_map": {str(k): v for k, v in RUN_MODE_READ_MAP.items()},
            "control_enabled": False,
        }


class PanasonicRawStatusSensor(PanasonicDeviceEntity, SensorEntity):
    """Disabled-by-default diagnostic count of reported fields."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:code-json"

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_translation_key = "reported_field_count"
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_raw_status"

    @property
    def native_value(self):
        """Return raw status field count."""
        return len(self.status)

    @property
    def extra_state_attributes(self):
        """Keep raw cloud status out of HA's state machine and history."""
        return {"protocol": self.device.profile or "unknown"}


class PanasonicProtocolSensor(PanasonicDeviceEntity, SensorEntity):
    """Show protocol matching status even for an unsupported model."""

    _attr_translation_key = "device_protocol"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:connection"

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_protocol"

    @property
    def native_value(self) -> str:
        return self.device.profile or "仅状态"

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.device.hardware_validation_pending:
            return {"verification": "未实机验证"}
        return None


class PanasonicBathroomTimer(PanasonicDeviceEntity, SensorEntity):
    """Report remaining running time when the device reports a finite timer."""

    _attr_name = "剩余运行时间"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_remaining_time"

    @property
    def native_value(self) -> int | None:
        hours = int_or_none(self.raw_value("timeHourLeft"))
        minutes = int_or_none(self.raw_value("timeMinuteLeft"))
        if (
            hours is not None
            and 0 <= hours < 13
            and minutes is not None
            and 0 <= minutes < 60
        ):
            return hours * 60 + minutes
        return None
