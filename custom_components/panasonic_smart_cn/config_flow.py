"""Config flow for Panasonic Smart CN."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api.auth import authenticate, make_client_id
from .api.client import SessionManager
from .const import (
    CONF_AUTO_RELOGIN,
    CONF_CLIENT_ID,
    CONF_DEV_SUB_TYPE_ID,
    CONF_DEVICE_MODEL,
    CONF_DEVICE_NAME,
    CONF_DEVICES,
    CONF_FAMILY_ID,
    CONF_REAL_FAMILY_ID,
    CONF_SESSION_ID,
    CONF_UPDATE_INTERVAL,
    CONF_USER_ID,
    DEFAULT_AUTO_RELOGIN,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    ENTRY_SCHEMA_VERSION,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)
from .exceptions import AuthenticationError, CloudError
from .protocol.payloads import hardware_validation_pending, match_profile


def login_schema():
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME): TextSelector(),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        }
    )


def login_data(session, client_id):
    return {
        CONF_USER_ID: session.user_id,
        CONF_SESSION_ID: session.session_id,
        CONF_FAMILY_ID: session.family_id,
        CONF_REAL_FAMILY_ID: session.real_family_id,
        CONF_CLIENT_ID: client_id,
    }


class PanasonicSmartConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow."""

    VERSION = ENTRY_SCHEMA_VERSION

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._login: dict[str, Any] = {}
        self._devices: dict[str, dict[str, Any]] = {}

    async def async_step_user(self, user_input=None):
        """Log in and discover fresh-air devices."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                session = await authenticate(
                    async_get_clientsession(self.hass),
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    make_client_id(user_input[CONF_USERNAME]),
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except aiohttp.ClientError, TimeoutError, CloudError, ValueError:
                errors["base"] = "cannot_connect"
            else:
                if not session.devices:
                    return self.async_abort(reason="no_devices_found")

                await self.async_set_unique_id(str(session.user_id))
                self._abort_if_unique_id_configured()
                self._credentials = {
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                self._login = login_data(
                    session, make_client_id(user_input[CONF_USERNAME])
                )
                self._devices = session.devices
                return await self.async_step_device()

        return self.async_show_form(
            step_id="user",
            data_schema=login_schema(),
            errors=errors,
        )

    async def async_step_device(self, user_input=None):
        """Select one or more devices already bound to this cloud account."""
        choices = []
        metadata = {}
        for device_id, info in self._devices.items():
            params = info["params"]
            subtype = params.get("devSubTypeId")
            model = params.get("deviceMNO")
            profile = match_profile(device_id, subtype, model)
            name = info.get("deviceName") or model or subtype or "Panasonic"
            details = " · ".join(
                dict.fromkeys(filter(None, (model, profile or "仅状态")))
            )
            if hardware_validation_pending(profile, model):
                details += " · 未实机验证"
            choices.append(
                SelectOptionDict(
                    value=device_id, label=f"{name}（{details} · {device_id[-6:]}）"
                )
            )
            metadata[device_id] = {
                CONF_DEVICE_NAME: name,
                CONF_DEV_SUB_TYPE_ID: subtype,
                CONF_DEVICE_MODEL: model,
            }

        reconfiguring = self.source == config_entries.SOURCE_RECONFIGURE
        if reconfiguring:
            entry = self._get_reconfigure_entry()
            defaults = [key for key in entry.data[CONF_DEVICES] if key in metadata]
        else:
            defaults = list(metadata)
        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICES, default=defaults): SelectSelector(
                    SelectSelectorConfig(
                        multiple=True, mode=SelectSelectorMode.DROPDOWN, options=choices
                    )
                )
            }
        )
        errors = {}
        if user_input is not None:
            selected = user_input[CONF_DEVICES]
            if selected and set(selected) <= metadata.keys():
                devices = {key: metadata[key] for key in selected}
                if reconfiguring:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_DEVICES: devices}
                    )
                return self.async_create_entry(
                    title="松下智能家电",
                    data={**self._credentials, **self._login, CONF_DEVICES: devices},
                )
            errors["base"] = "choose_device"
        return self.async_show_form(step_id="device", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input=None):
        """Refresh the device list when the user explicitly reconfigures."""
        entry = self._get_reconfigure_entry()
        coordinator = getattr(entry, "runtime_data", None)
        session = (
            coordinator.session if coordinator else SessionManager(self.hass, entry)
        )
        try:
            self._devices = await session.devices()
        except AuthenticationError:
            return self.async_abort(reason="reauth_required")
        except aiohttp.ClientError, TimeoutError, CloudError, ValueError:
            return self.async_abort(reason="cannot_connect")
        if not self._devices:
            return self.async_abort(reason="no_devices_found")
        return await self.async_step_device()

    async def async_step_reauth(self, entry_data):
        """Route expired cloud credentials through HA's reauthentication UI."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            client_id = entry.data.get(CONF_CLIENT_ID) or make_client_id(
                entry.data[CONF_USERNAME]
            )
            try:
                session = await authenticate(
                    async_get_clientsession(self.hass),
                    entry.data[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    client_id,
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except aiohttp.ClientError, TimeoutError, CloudError, ValueError:
                errors["base"] = "cannot_connect"
            else:
                if str(entry.data.get(CONF_USER_ID)) != str(session.user_id):
                    return self.async_abort(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry, data_updates={**login_data(session, client_id), **user_input}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return options flow."""
        return PanasonicSmartOptionsFlow()


class PanasonicSmartOptionsFlow(config_entries.OptionsFlow):
    """Options flow."""

    async def async_step_init(self, user_input=None):
        """Edit polling interval."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_AUTO_RELOGIN,
                        default=self.config_entry.options.get(
                            CONF_AUTO_RELOGIN,
                            self.config_entry.data.get(
                                CONF_AUTO_RELOGIN,
                                DEFAULT_AUTO_RELOGIN,
                            ),
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL,
                            DEFAULT_UPDATE_INTERVAL,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                    ),
                }
            ),
        )
