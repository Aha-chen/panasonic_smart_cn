"""Button platform."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity

from .const import DOMAIN
from .entity import PanasonicDeviceEntity
from .protocol.erv import LEGACY_AIRCLE


@dataclass(frozen=True)
class ButtonSpec:
    field: str
    name: str
    unique_suffix: str
    icon: str


BUTTONS: tuple[ButtonSpec, ...] = (
    ButtonSpec("clFilReset", "过滤网清洁复位", "clean_filter_reset", "mdi:air-filter"),
    ButtonSpec(
        "resFilExReset", "初效过滤网更换复位", "res_filter_reset", "mdi:air-filter"
    ),
    ButtonSpec(
        "oaFilExReset", "新风集尘过滤网更换复位", "oa_filter_reset", "mdi:air-filter"
    ),
    ButtonSpec(
        "saFilExReset", "送风集尘过滤网更换复位", "sa_filter_reset", "mdi:air-filter"
    ),
    ButtonSpec(
        "raFilExReset", "回风过滤网更换复位", "ra_filter_reset", "mdi:air-filter"
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up buttons."""
    coordinator = entry.runtime_data
    for device in coordinator.devices.values():
        _add_device_entities(coordinator, device, async_add_entities)


def _add_device_entities(coordinator, device, async_add_entities):
    if device.profile == LEGACY_AIRCLE:
        async_add_entities(
            [PanasonicResetButton(coordinator, device, spec) for spec in BUTTONS]
        )


class PanasonicResetButton(PanasonicDeviceEntity, ButtonEntity):
    """One-shot reset button."""

    def __init__(self, coordinator, device, spec: ButtonSpec) -> None:
        super().__init__(coordinator, device)
        self._spec = spec
        self._attr_name = spec.name
        self._attr_icon = spec.icon
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_{spec.unique_suffix}"

    @property
    def extra_state_attributes(self):
        """Expose the reset field used by the protocol."""
        return {
            "field": self._spec.field,
            "raw_value": self.raw_value(self._spec.field),
        }

    async def async_press(self) -> None:
        """Trigger reset."""
        await self.async_set_fields({self._spec.field: 1})
