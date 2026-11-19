"""Privacy-preserving diagnostics for Panasonic Smart CN."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as core_version
from homeassistant.core import HomeAssistant


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Report device protocol and polling outcomes without account data."""
    coordinator = getattr(entry, "runtime_data", None)
    devices = []
    polling_ok = None
    if coordinator is not None:
        polling_ok = coordinator.last_update_success
        statuses = coordinator.data or {}
        devices = [
            {
                "protocol": device.profile,
                "control_supported": device.profile is not None,
                "hardware_validation_pending": device.hardware_validation_pending,
                "status_received": device.device_id in statuses,
                "status_field_count": len(statuses.get(device.device_id, {})),
            }
            for device in coordinator.devices.values()
        ]
    return {
        "home_assistant_core": core_version,
        "polling_ok": polling_ok,
        "devices": devices,
    }
