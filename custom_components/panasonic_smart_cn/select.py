"""Select platform."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .entity import PanasonicDeviceEntity
from .protocol.appliances import BATH_MODES, bath_mode
from .protocol.erv import LEGACY_AIRCLE
from .protocol.mappings import (
    EXHAUST_STRENGTH_MAP,
    EXHAUST_STRENGTH_SET_MAP,
    PM25_THRESHOLD_MAP,
    PM25_THRESHOLD_SET_MAP,
    PRESSURE_MODE_MAP,
    PRESSURE_MODE_SET_MAP,
    int_or_none,
    mapped_option,
)
from .protocol.payloads import display_options, fixed_air_volume


@dataclass(frozen=True)
class SelectSpec:
    field: str
    name: str | None
    unique_suffix: str
    value_map: dict[int, str]
    set_map: dict[str, int]
    icon: str
    requires_custom_pressure_mode: bool = False
    block_in_holiday_mode: bool = True
    translation_key: str | None = None


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up select entities."""
    coordinator = entry.runtime_data
    for device in coordinator.devices.values():
        _add_device_entities(coordinator, device, async_add_entities)


def _add_device_entities(coordinator, device, async_add_entities):
    if device.profile is None:
        return
    if device.profile in BATH_MODES:
        async_add_entities([PanasonicBathroomMode(coordinator, device)])
        return
    if device.appliance:
        return
    modes, mode_writes, speeds = display_options(device.profile)
    air_speed = SelectSpec(
        "airVo",
        "风量",
        "air_volume",
        speeds,
        {label: raw for raw, label in speeds.items()},
        "mdi:weather-windy",
    )
    entities = [PanasonicMappedSelect(coordinator, device, air_speed)]
    if mode_writes:
        mode = SelectSpec(
            "runM",
            None,
            "run_mode_select",
            modes,
            mode_writes,
            "mdi:fan-auto",
            translation_key="operating_mode",
        )
        entities.append(PanasonicMappedSelect(coordinator, device, mode))
    if device.profile == LEGACY_AIRCLE:
        entities.extend(
            [
                PanasonicMappedSelect(
                    coordinator,
                    device,
                    SelectSpec(
                        "preSet",
                        "运转设定",
                        "pressure_mode",
                        PRESSURE_MODE_MAP,
                        PRESSURE_MODE_SET_MAP,
                        "mdi:fan-plus",
                    ),
                ),
                PanasonicMappedSelect(
                    coordinator,
                    device,
                    SelectSpec(
                        "pmSen",
                        "室内侧 PM2.5 阈值",
                        "pm25_threshold",
                        PM25_THRESHOLD_MAP,
                        PM25_THRESHOLD_SET_MAP,
                        "mdi:blur",
                    ),
                ),
                PanasonicMappedSelect(
                    coordinator,
                    device,
                    SelectSpec(
                        "slfOutW",
                        "排风强度",
                        "exhaust_strength",
                        EXHAUST_STRENGTH_MAP,
                        EXHAUST_STRENGTH_SET_MAP,
                        "mdi:fan-chevron-down",
                        requires_custom_pressure_mode=True,
                    ),
                ),
            ]
        )
    async_add_entities(entities)


class PanasonicMappedSelect(PanasonicDeviceEntity, SelectEntity):
    """Mapped fresh-air select."""

    def __init__(self, coordinator, device, spec: SelectSpec) -> None:
        super().__init__(coordinator, device)
        self._spec = spec
        if spec.name is not None:
            self._attr_name = spec.name
        self._attr_translation_key = spec.translation_key
        self._attr_icon = spec.icon
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_{spec.unique_suffix}"
        self._attr_options = list(spec.set_map)

    @property
    def current_option(self):
        """Return current mapped value."""
        option = mapped_option(self.raw_value(self._spec.field), self._spec.value_map)
        if self._fixed_volume is not None and option not in self.options:
            return None
        return option

    @property
    def _fixed_volume(self) -> int | None:
        if self._spec.field == "airVo":
            return fixed_air_volume(self.device.profile, self.raw_value("runM"))
        return None

    @property
    def options(self) -> list[str]:
        if (fixed := self._fixed_volume) is not None:
            return [self._spec.value_map[fixed]]
        return self._attr_options

    @property
    def available(self) -> bool:
        """Return whether the select can currently be controlled."""
        if not super().available:
            return False
        if (
            self._spec.requires_custom_pressure_mode
            and int_or_none(self.raw_value("preSet")) != 2
        ):
            return False
        return True

    @property
    def extra_state_attributes(self):
        """Expose raw value and mapping."""
        attrs = {
            "field": self._spec.field,
            "raw_value": self.raw_value(self._spec.field),
            "value_map": {str(k): v for k, v in self._spec.value_map.items()},
            "holiday_mode": int_or_none(self.raw_value("holM")) == 1,
            "disinfection_mode": int_or_none(self.raw_value("runM")) == 7,
        }
        if self._spec.requires_custom_pressure_mode:
            attrs["requires_pressure_mode"] = "自定义模式"
        if self._spec.field == "airVo":
            attrs["air_volume_locked"] = self._fixed_volume is not None
        return attrs

    async def async_select_option(self, option: str) -> None:
        """Set mapped field."""
        if (
            self._spec.block_in_holiday_mode
            and int_or_none(self.raw_value("holM")) == 1
        ):
            raise HomeAssistantError("度假模式下只允许关闭度假模式")
        if self._fixed_volume is not None:
            if option in self.options:
                return
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="air_volume_locked"
            )
        if (
            self._spec.requires_custom_pressure_mode
            and int_or_none(self.raw_value("preSet")) != 2
        ):
            raise HomeAssistantError("只有自定义模式下可以设置排风强度")

        value = self._spec.set_map.get(option)
        if value is None:
            raise HomeAssistantError(f"未知选项: {option}")
        await self.async_set_fields({self._spec.field: value})


class PanasonicBathroomMode(PanasonicDeviceEntity, SelectEntity):
    """Select a bathroom heater's operating mode, including exhaust."""

    _attr_name = "运行模式"
    _attr_icon = "mdi:hvac"

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._mode_codes = {
            label: raw for raw, label in BATH_MODES[device.profile].items()
        }
        self._attr_options = list(self._mode_codes)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_bath_mode"

    @property
    def current_option(self) -> str | None:
        raw = int_or_none(self.raw_value("runningMode"))
        return bath_mode(self.device.profile, raw)

    async def async_select_option(self, option: str) -> None:
        if option not in self._mode_codes:
            raise HomeAssistantError("此型号不支持该运行模式")
        await self.async_set_fields({"runningMode": self._mode_codes[option]})
