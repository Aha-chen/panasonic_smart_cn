"""Panasonic Smart CN integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry

from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN, PLATFORMS
from .coordinator import PanasonicAccountCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Panasonic fresh-air device."""
    coordinator = PanasonicAccountCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    registry = device_registry.async_get(hass)
    for device in device_registry.async_entries_for_config_entry(
        registry, entry.entry_id
    ):
        if any(
            domain == DOMAIN and key not in coordinator.devices
            for domain, key in device.identifiers
        ):
            registry.async_remove_device(device.id)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    interval = timedelta(
        seconds=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    )
    if entry.runtime_data.update_interval != interval:
        await hass.config_entries.async_reload(entry.entry_id)
