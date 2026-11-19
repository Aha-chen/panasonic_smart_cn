"""One Home Assistant data coordinator per Panasonic cloud account."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import PanasonicFreshAirClient, SessionManager
from .const import CONF_DEVICES, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .exceptions import AuthenticationError, CloudError

_LOGGER = logging.getLogger(__name__)


class PanasonicAccountCoordinator(DataUpdateCoordinator[dict[str, dict]]):
    """Poll the selected devices using a shared cloud session."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._controls_during_refresh: dict[str, dict] | None = None
        self.session = SessionManager(hass, entry)
        self.devices = {
            device_id: PanasonicFreshAirClient(self.session, device_id, metadata)
            for device_id, metadata in entry.data[CONF_DEVICES].items()
        }
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            ),
        )

    async def async_control_device(
        self, device: PanasonicFreshAirClient, fields: dict[str, int]
    ) -> None:
        """Publish a confirmed readback without polling the other devices."""
        status = await device.set_fields(fields)
        if status is None or not self.last_update_success:
            await self.async_request_refresh()
            return
        if self._controls_during_refresh is not None:
            self._controls_during_refresh[device.device_id] = status
        self.async_set_updated_data({**self.data, device.device_id: status})

    async def _async_update_data(self) -> dict[str, dict]:
        self._controls_during_refresh = {}
        try:
            inventory = await self.session.devices()
            statuses = await self._read_devices(inventory)
            # A slower account poll can finish after a confirmed control.
            return {**statuses, **self._controls_during_refresh}
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (aiohttp.ClientError, TimeoutError, CloudError, ValueError) as err:
            raise UpdateFailed(str(err)) from err
        finally:
            self._controls_during_refresh = None

    async def _read_devices(self, inventory: dict) -> dict[str, dict]:
        selected = [
            device for device in self.devices.values() if device.device_id in inventory
        ]
        result = await asyncio.gather(
            *(
                device.fetch_status(
                    inventory[device.device_id]["params"].get("statusAll") or {}
                )
                for device in selected
            ),
            return_exceptions=True,
        )
        statuses = {}
        for device, status in zip(selected, result, strict=True):
            if isinstance(status, AuthenticationError):
                raise status
            if isinstance(
                status, (CloudError, aiohttp.ClientError, TimeoutError, ValueError)
            ):
                _LOGGER.debug("Unable to read %s device: %s", device.profile, status)
                continue
            if isinstance(status, BaseException):
                raise status
            statuses[device.device_id] = status
        return statuses
