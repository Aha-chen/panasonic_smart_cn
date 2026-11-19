"""Native Home Assistant fan for supported Panasonic ventilation devices."""

from __future__ import annotations

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .const import DOMAIN
from .entity import PanasonicDeviceEntity
from .protocol.appliances import PURIFIER_PXP, PURIFIER_VXR
from .protocol.erv import LEGACY_AIRCLE
from .protocol.mappings import int_or_none
from .protocol.payloads import display_options, fixed_air_volume


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        PanasonicVentilationFan(coordinator, device)
        for device in coordinator.devices.values()
        if device.profile is not None and device.appliance is None
    )
    async_add_entities(
        PanasonicPurifierFan(coordinator, device)
        for device in coordinator.devices.values()
        if device.profile in {PURIFIER_PXP, PURIFIER_VXR}
    )


class PanasonicVentilationFan(PanasonicDeviceEntity, FanEntity):
    _attr_name = None
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_fan"
        self.modes, self.mode_writes, self.speeds = display_options(device.profile)
        self._attr_speed_count = len(self.speeds)
        self._attr_preset_modes = list(self.mode_writes)
        self._attr_supported_features = (
            FanEntityFeature.TURN_ON
            | FanEntityFeature.TURN_OFF
            | FanEntityFeature.SET_SPEED
        )
        if self.mode_writes:
            self._attr_supported_features |= FanEntityFeature.PRESET_MODE

    @property
    def is_on(self) -> bool | None:
        value = int_or_none(self.raw_value("runSta"))
        return bool(value) if value in (0, 1) else None

    @property
    def percentage(self) -> int | None:
        if self.is_on is False:
            return 0
        speed = int_or_none(self.raw_value("airVo"))
        if speed not in self.speeds:
            return None
        return ordered_list_item_to_percentage(list(self.speeds), speed)

    @property
    def preset_mode(self) -> str | None:
        mode = self.modes.get(int_or_none(self.raw_value("runM")))
        return mode if mode in self.mode_writes else None

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "speed_label": self.speeds.get(int_or_none(self.raw_value("airVo"))),
            "air_volume_locked": self._air_volume_locked,
        }

    @property
    def _air_volume_locked(self) -> bool:
        return fixed_air_volume(self.device.profile, self.raw_value("runM")) is not None

    @property
    def supported_features(self) -> FanEntityFeature:
        if self._air_volume_locked:
            return self._attr_supported_features & ~FanEntityFeature.SET_SPEED
        return self._attr_supported_features

    def _ensure_can_control(self) -> None:
        if int_or_none(self.raw_value("holM")) == 1:
            raise HomeAssistantError("度假模式下只允许关闭度假模式")

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return
        self._ensure_can_control()
        fields = {"runSta": 1}
        if self.device.profile == LEGACY_AIRCLE:
            fields["runM"] = self.mode_writes.get(self.preset_mode, 6)
        if preset_mode is not None:
            if preset_mode not in self.mode_writes:
                raise HomeAssistantError("此设备不支持该运行模式")
            fields["runM"] = self.mode_writes[preset_mode]
        if (
            self.device.profile == LEGACY_AIRCLE
            and fixed_air_volume(self.device.profile, fields["runM"]) is None
        ):
            speed = int_or_none(self.raw_value("airVo"))
            fields["airVo"] = speed if speed in self.speeds else 0
        if percentage is not None:
            fields["airVo"] = percentage_to_ordered_list_item(
                list(self.speeds), percentage
            )
        await self.async_set_fields(fields)

    async def async_turn_off(self, **kwargs) -> None:
        self._ensure_can_control()
        await self.async_set_fields({"runSta": 0})

    async def async_set_percentage(self, percentage: int) -> None:
        if not percentage:
            await self.async_turn_off()
        elif self.is_on is not True:
            await self.async_turn_on(percentage=percentage)
        else:
            self._ensure_can_control()
            speed = percentage_to_ordered_list_item(list(self.speeds), percentage)
            await self.async_set_fields({"airVo": speed})

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        self._ensure_can_control()
        if preset_mode not in self.mode_writes:
            raise HomeAssistantError("此设备不支持该运行模式")
        await self.async_set_fields({"runM": self.mode_writes[preset_mode]})


class PanasonicPurifierFan(PanasonicDeviceEntity, FanEntity):
    """Native fan control for the two cloud air-purifier families."""

    _attr_name = None
    _attr_icon = "mdi:air-purifier"
    _enable_turn_on_off_backwards_compatibility = False
    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
    )

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_purifier"
        self._humidifying_model = device.profile == PURIFIER_VXR
        if self._humidifying_model:
            self._speeds = {1: "轻柔", 2: "中速", 3: "高速", 4: "急速"}
            self._presets = {"舒缓模式": 1, "儿童模式": 11, "自动": 12}
        else:
            self._speeds = {1: "低速", 2: "中速", 3: "高速"}
            self._presets = {"自动": 0}
        self._attr_speed_count = len(self._speeds)
        self._attr_preset_modes = list(self._presets)

    @property
    def is_on(self) -> bool | None:
        raw = int_or_none(self.raw_value("runningStatus"))
        return bool(raw) if raw in (0, 1) else None

    @property
    def preset_mode(self) -> str | None:
        if self.is_on is not True:
            return None
        field = "runningMode" if self._humidifying_model else "airVolume"
        raw = int_or_none(self.raw_value(field))
        return next(
            (label for label, value in self._presets.items() if value == raw), None
        )

    @property
    def percentage(self) -> int | None:
        if self.is_on is False:
            return 0
        raw = int_or_none(self.raw_value("airVolume"))
        if self.preset_mode or raw not in self._speeds:
            return None
        return ordered_list_item_to_percentage(list(self._speeds), raw)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "speed_label": self.preset_mode
            or self._speeds.get(int_or_none(self.raw_value("airVolume")))
        }

    def _speed_fields(self, percentage: int) -> dict:
        raw = percentage_to_ordered_list_item(list(self._speeds), percentage)
        fields = {"airVolume": raw}
        if self._humidifying_model:
            fields["runningMode"] = 0
        return fields

    def _preset_fields(self, label: str) -> dict:
        if label not in self._presets:
            raise HomeAssistantError("此型号不支持该运行模式")
        field = "runningMode" if self._humidifying_model else "airVolume"
        return {field: self._presets[label]}

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return
        fields = {"runningStatus": 1}
        if preset_mode is not None:
            fields.update(self._preset_fields(preset_mode))
        elif percentage is not None:
            fields.update(self._speed_fields(percentage))
        await self.async_set_fields(fields)

    async def async_turn_off(self, **kwargs) -> None:
        await self.async_set_fields({"runningStatus": 0})

    async def async_set_percentage(self, percentage: int) -> None:
        if not percentage:
            await self.async_turn_off()
        elif self.is_on is not True:
            await self.async_turn_on(percentage=percentage)
        else:
            await self.async_set_fields(self._speed_fields(percentage))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if self.is_on is not True:
            await self.async_turn_on(preset_mode=preset_mode)
        else:
            await self.async_set_fields(self._preset_fields(preset_mode))
