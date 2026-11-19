"""Shared entity behavior for Panasonic cloud devices."""

from __future__ import annotations

import aiohttp
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEV_SUB_TYPE_ID, CONF_DEVICE_MODEL, CONF_DEVICE_NAME, DOMAIN
from .coordinator import PanasonicAccountCoordinator
from .exceptions import (
    AirVolumeLockedError,
    ControlNotConfirmedError,
    PanasonicFreshAirError,
)


class PanasonicDeviceEntity(CoordinatorEntity[PanasonicAccountCoordinator]):
    """Associate an entity with an account and one device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, context=device.device_id)
        self.device = device
        self._device_id = device.device_id
        model = device.metadata.get(CONF_DEVICE_MODEL)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=device.metadata[CONF_DEVICE_NAME],
            manufacturer="Panasonic",
            model=model or device.metadata.get(CONF_DEV_SUB_TYPE_ID) or None,
        )

    @property
    def status(self) -> dict:
        return (self.coordinator.data or {}).get(self._device_id, {})

    @property
    def available(self) -> bool:
        return super().available and self._device_id in (self.coordinator.data or {})

    def raw_value(self, key: str):
        return self.status.get(key)

    async def async_set_fields(self, fields: dict[str, int]) -> None:
        try:
            await self.coordinator.async_control_device(self.device, fields)
        except AirVolumeLockedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="air_volume_locked",
            ) from err
        except ControlNotConfirmedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="control_not_confirmed",
            ) from err
        except (PanasonicFreshAirError, aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="control_failed",
            ) from err
