"""Native light entity for the FV-RB20VL1 bathroom heater."""

from homeassistant.components.light import ColorMode, LightEntity

from .const import DOMAIN
from .entity import PanasonicDeviceEntity
from .protocol.appliances import BATH_RB20
from .protocol.mappings import int_or_none


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        PanasonicBathroomLight(coordinator, device)
        for device in coordinator.devices.values()
        if device.profile == BATH_RB20
    )


class PanasonicBathroomLight(PanasonicDeviceEntity, LightEntity):
    """Bathroom light with an independent on/off control."""

    _attr_name = "照明"
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_light"

    @property
    def is_on(self) -> bool | None:
        value = int_or_none(self.raw_value("lightSet"))
        return bool(value) if value in (0, 1) else None

    async def async_turn_on(self, **kwargs) -> None:
        await self.async_set_fields({"lightSet": 1})

    async def async_turn_off(self, **kwargs) -> None:
        await self.async_set_fields({"lightSet": 0})
