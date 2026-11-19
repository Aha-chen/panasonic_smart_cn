"""Switch platform."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .entity import PanasonicDeviceEntity
from .protocol.appliances import PURIFIER_VXR
from .protocol.erv import LEGACY_AIRCLE
from .protocol.mappings import int_or_none
from .protocol.payloads import core_controls


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up switches."""
    coordinator = entry.runtime_data
    for device in coordinator.devices.values():
        _add_device_entities(coordinator, device, async_add_entities)


def _add_device_entities(coordinator, device, async_add_entities):
    if device.profile == PURIFIER_VXR:
        async_add_entities(
            [
                PanasonicFieldSwitch(
                    coordinator,
                    device,
                    "humidification",
                    "加湿",
                    "humidification",
                    "mdi:water-percent",
                )
            ]
        )
        return
    if device.profile != LEGACY_AIRCLE:
        fields = core_controls(device.profile)
        switches = []
        if "nanoe" in fields:
            switches.append(
                PanasonicFieldSwitch(
                    coordinator,
                    device,
                    "nanoe",
                    "nanoe",
                    "nanoe",
                    "mdi:air-filter",
                    block_in_holiday_mode=True,
                )
            )
        async_add_entities(switches)
        return
    async_add_entities(
        [
            PanasonicFieldSwitch(
                coordinator, device, "holM", "度假模式", "holiday", "mdi:beach"
            ),
            PanasonicFieldSwitch(
                coordinator,
                device,
                "breathLight",
                "呼吸灯",
                "breath_light",
                "mdi:lightbulb-outline",
                block_in_holiday_mode=True,
            ),
        ]
    )


class PanasonicFieldSwitch(PanasonicDeviceEntity, SwitchEntity):
    """Boolean field switch."""

    def __init__(
        self,
        coordinator,
        device,
        field: str,
        name: str,
        suffix: str,
        icon: str,
        *,
        block_in_holiday_mode: bool = False,
    ) -> None:
        super().__init__(coordinator, device)
        self._field = field
        self._block_in_holiday_mode = block_in_holiday_mode
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_{suffix}"

    @property
    def is_on(self):
        """Return current switch state."""
        value = int_or_none(self.raw_value(self._field))
        if value is None or value == 255:
            return None
        return value == 1

    @property
    def extra_state_attributes(self):
        """Expose raw value."""
        return {
            "field": self._field,
            "raw_value": self.raw_value(self._field),
            "holiday_mode": int_or_none(self.raw_value("holM")) == 1,
        }

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on field."""
        self._ensure_can_control()
        fields = {self._field: 1}
        await self.async_set_fields(fields)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off field."""
        self._ensure_can_control()
        await self.async_set_fields({self._field: 0})

    def _ensure_can_control(self) -> None:
        """Reject controls the mobile app also locks while holiday mode is on."""
        if self._block_in_holiday_mode and int_or_none(self.raw_value("holM")) == 1:
            raise HomeAssistantError("度假模式下只允许关闭度假模式")
