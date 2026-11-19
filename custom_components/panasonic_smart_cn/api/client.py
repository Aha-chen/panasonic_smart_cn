"""Panasonic Smart China client."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import (
    AUTH_EXPIRED_CODES,
    CONF_AUTO_RELOGIN,
    CONF_CLIENT_ID,
    CONF_DEV_SUB_TYPE_ID,
    CONF_DEVICE_MODEL,
    CONF_FAMILY_ID,
    CONF_REAL_FAMILY_ID,
    CONF_SESSION_ID,
    CONF_USER_ID,
    DEFAULT_AUTO_RELOGIN,
    DOMAIN,
)
from ..exceptions import (
    AirVolumeLockedError,
    AuthenticationError,
    CloudError,
    ControlNotConfirmedError,
)
from ..protocol.appliances import APPLIANCE_PROTOCOLS, bath_mode, write_params
from ..protocol.device_id import generate_device_token
from ..protocol.erv import ERV_PROTOCOLS
from ..protocol.mappings import int_or_none
from ..protocol.payloads import (
    fixed_air_volume,
    hardware_validation_pending,
    match_profile,
)
from .auth import (
    CLOUD_TLS,
    HEADERS,
    PanasonicSession,
    authenticate,
    fetch_devices,
    make_client_id,
)

_LOGGER = logging.getLogger(__name__)

RELOGIN_COOLDOWN_SECONDS = 600
MAX_SET_RETRIES = 3
MODE_READBACK_GRACE = 15
CONTROL_READBACK_DELAYS = (0.5, 1.5, 3.0)
CONTROL_READBACK_TIMEOUT = 15


def _extract_error_code(data: dict[str, Any] | None) -> str | None:
    if not isinstance(data, dict):
        return None
    if data.get("errorCode") is not None:
        return str(data["errorCode"])
    error = data.get("error")
    if isinstance(error, dict) and error.get("code") is not None:
        return str(error["code"])
    return None


def response_failed(data: dict[str, Any] | None) -> bool:
    """Return whether a cloud response is not a successful data response."""
    if not isinstance(data, dict):
        return True
    code = _extract_error_code(data)
    if code is not None and code not in ("0", ""):
        return True
    return "results" not in data


def auth_expired(data: dict[str, Any] | None) -> bool:
    """Return whether a response indicates an expired session."""
    code = _extract_error_code(data)
    return code in AUTH_EXPIRED_CODES


class SessionManager:
    """Coordinate login and silent relogin for a config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        domain_data = hass.data.setdefault(DOMAIN, {})
        locks = domain_data.setdefault("session_locks", {})
        self._lock: asyncio.Lock = locks.setdefault(entry.entry_id, asyncio.Lock())

    @property
    def session_id(self) -> str:
        """Current stored session id."""
        return self.entry.data[CONF_SESSION_ID]

    async def relogin(self, *, force: bool = False) -> str:
        """Refresh session id and persist it in the config entry.

        Cooldown starts only after a successful login. If another coroutine has
        already refreshed the same entry, this returns the already refreshed id.
        """
        async with self._lock:
            auto_relogin = self.entry.options.get(
                CONF_AUTO_RELOGIN,
                self.entry.data.get(CONF_AUTO_RELOGIN, DEFAULT_AUTO_RELOGIN),
            )
            if not force and not auto_relogin:
                raise AuthenticationError(
                    "Panasonic session expired; automatic relogin is disabled to avoid kicking the mobile app"
                )

            domain_data = self.hass.data.setdefault(DOMAIN, {})
            success_key = f"last_successful_relogin:{self.entry.entry_id}"
            last_success = domain_data.get(success_key, 0.0)
            now = time.monotonic()
            if (
                not force
                and last_success
                and now - last_success < RELOGIN_COOLDOWN_SECONDS
            ):
                return self.entry.data[CONF_SESSION_ID]

            username = self.entry.data.get(CONF_USERNAME)
            password = self.entry.data.get(CONF_PASSWORD)
            if not username or not password:
                raise AuthenticationError("Missing stored Panasonic credentials")
            client_id = self.entry.data.get(CONF_CLIENT_ID) or make_client_id(username)

            http = async_get_clientsession(self.hass)
            session = await authenticate(http, username, password, client_id)
            self._store_session(session, client_id)
            domain_data[success_key] = time.monotonic()
            _LOGGER.info("Refreshed Panasonic session for %s", self.entry.entry_id)
            return session.session_id

    async def devices(self) -> dict:
        """Fetch the cloud device list once per account refresh."""
        http = async_get_clientsession(self.hass)
        data = self.entry.data
        try:
            return await fetch_devices(
                http,
                data[CONF_USER_ID],
                self.session_id,
                data.get(CONF_FAMILY_ID),
                data.get(CONF_REAL_FAMILY_ID),
            )
        except AuthenticationError:
            await self.relogin()
            data = self.entry.data
            return await fetch_devices(
                http,
                data[CONF_USER_ID],
                self.session_id,
                data.get(CONF_FAMILY_ID),
                data.get(CONF_REAL_FAMILY_ID),
            )

    def _store_session(self, session: PanasonicSession, client_id: str) -> None:
        new_data = {
            **self.entry.data,
            CONF_CLIENT_ID: client_id,
            CONF_USER_ID: session.user_id,
            CONF_SESSION_ID: session.session_id,
            CONF_FAMILY_ID: session.family_id,
            CONF_REAL_FAMILY_ID: session.real_family_id,
        }
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)


class PanasonicFreshAirClient:
    """High-level client for one fresh-air device."""

    def __init__(self, session: SessionManager, device_id: str, metadata: dict) -> None:
        self.hass = session.hass
        self.entry = session.entry
        self.session_manager = session
        self.device_id = device_id
        self.metadata = metadata
        self.token = generate_device_token(device_id)
        self.profile = match_profile(
            device_id,
            metadata.get(CONF_DEV_SUB_TYPE_ID),
            metadata.get(CONF_DEVICE_MODEL),
        )
        self.hardware_validation_pending = hardware_validation_pending(
            self.profile, metadata.get(CONF_DEVICE_MODEL)
        )
        self.erv = ERV_PROTOCOLS.get(self.profile)
        self.appliance = APPLIANCE_PROTOCOLS.get(self.profile)
        self._request_id = 0
        self._write_lock = asyncio.Lock()
        self._status: dict[str, Any] = {}
        self._fixed_speed_pending_until = 0.0

    async def fetch_status(self, cached: dict[str, Any]) -> dict[str, Any]:
        """Read this device using the selected protocol."""
        async with self._write_lock:
            if self.appliance:
                status = await self._read_appliance()
            elif self.erv and self.erv.live_status:
                status = await self._fetch_live_status(self.profile)
                if aux_keys := self.erv.auxiliary_keys:
                    try:
                        auxiliary = await self._fetch_live_status("MIDERV")
                    except CloudError, aiohttp.ClientError, TimeoutError, ValueError:
                        auxiliary = {}
                    for key in aux_keys:
                        status.pop(key, None)
                        if key in auxiliary:
                            status[key] = auxiliary[key]
            else:
                status = cached
            return self._remember_status(status)

    def _remember_status(self, status: dict) -> dict:
        self._status = status
        if fixed_air_volume(self.profile, status.get("runM")) is not None:
            self._fixed_speed_pending_until = 0.0
        return status

    def _identity(self) -> dict:
        return {
            "deviceId": self.device_id,
            "token": self.token,
            "usrId": self.entry.data[CONF_USER_ID],
        }

    async def _fetch_live_status(self, name: str) -> dict[str, Any]:
        protocol = ERV_PROTOCOLS[name]
        response = await self._post_with_relogin(
            protocol.read_url,
            lambda: protocol.read_body(self._identity()),
            xtoken=protocol.info_format,
            referer=protocol.referer,
        )
        if response_failed(response):
            raise CloudError(f"无法读取 {name} 设备状态")
        status = protocol.decode_status(response["results"])
        if status is None:
            raise CloudError(f"{name} 返回了无法识别的设备状态")
        return status

    async def _post_with_relogin(
        self,
        url: str,
        body: Callable[[], dict],
        *,
        xtoken: bool,
        referer: str | None,
        allow_empty: bool = False,
    ) -> dict:
        kwargs = {"xtoken": xtoken, "referer": referer, "allow_empty": allow_empty}
        response = await self._post(url, body(), **kwargs)
        if auth_expired(response):
            await self.session_manager.relogin()
            response = await self._post(url, body(), **kwargs)
        if auth_expired(response):
            raise AuthenticationError("松下登录会话已失效")
        return response

    async def _read_appliance(self) -> dict:
        response = await self._post_with_relogin(
            self.appliance.read_url,
            lambda: {"id": self.appliance.status_id, **self._identity()},
            xtoken=True,
            referer=self.appliance.web_path,
        )
        status = self.appliance.decode_status(response.get("results"))
        if response_failed(response) or status is None:
            raise CloudError(f"无法读取 {self.profile} 设备状态")
        return status

    async def _write_appliance(self, fields: dict[str, int]) -> dict:
        status = self._status
        if not status or status.get("offline") in (1, "1"):
            raise CloudError("设备未连接或尚未取得有效状态")
        params = write_params(self.profile, fields, status)
        response = await self._post_with_relogin(
            self.appliance.write_url,
            lambda: {
                "id": self.appliance.write_id,
                **self._identity(),
                "params": params,
            },
            xtoken=True,
            referer=self.appliance.web_path,
            allow_empty=self.appliance.allow_empty_write,
        )
        if response.get("error") or _extract_error_code(response) not in (
            None,
            "0",
            "",
        ):
            raise CloudError("松下云未确认控制请求")
        return response

    async def set_fields(self, fields: dict[str, int]) -> dict[str, Any] | None:
        """Submit a command, then confirm persistent values with readback."""
        async with self._write_lock:
            await self._set_fields(fields)
            expected = fields.copy()
            if self.erv:
                for key in self.erv.action_fields:
                    expected.pop(key, None)
                if (
                    speed := self.erv.fixed_speeds.get(expected.get("runM"))
                ) is not None:
                    expected["airVo"] = speed
            if not expected:
                return None
            try:
                async with asyncio.timeout(CONTROL_READBACK_TIMEOUT):
                    for delay in CONTROL_READBACK_DELAYS:
                        await asyncio.sleep(delay)
                        try:
                            status = await self._read_control_status()
                        except (
                            CloudError,
                            aiohttp.ClientError,
                            TimeoutError,
                            ValueError,
                        ):
                            continue
                        if not status:
                            continue
                        self._remember_status(status)
                        if status.get("offline") not in (1, "1") and all(
                            self._control_value_matches(key, value, status.get(key))
                            for key, value in expected.items()
                        ):
                            return status
            except AuthenticationError as err:
                raise ControlNotConfirmedError from err
            except TimeoutError:
                pass
            _LOGGER.debug(
                "Control readback did not confirm %s fields %s",
                self.profile,
                tuple(expected),
            )
            raise ControlNotConfirmedError

    async def _read_control_status(self) -> dict:
        if self.appliance:
            return await self._read_appliance()
        if self.erv.live_status:
            status = await self._fetch_live_status(self.profile)
            for key in self.erv.auxiliary_keys:
                status.pop(key, None)
                if key in self._status:
                    status[key] = self._status[key]
            return status
        inventory = await self.session_manager.devices()
        return (
            inventory.get(self.device_id, {}).get("params", {}).get("statusAll") or {}
        )

    def _control_value_matches(self, key: str, expected: int, raw) -> bool:
        actual = int_or_none(raw)
        if actual is None:
            return False
        if key == "runningMode" and self.appliance and self.appliance.bath_modes:
            mode = bath_mode(self.profile, expected)
            return mode is not None and mode == bath_mode(self.profile, actual)
        if key == "runM" and self.erv:
            mode = self.erv.modes.get(expected)
            if mode is not None:
                return mode == self.erv.modes.get(actual)
        return expected == actual

    async def _set_fields(self, fields: dict[str, int]) -> dict[str, Any]:
        if not self.token:
            raise CloudError("设备标识无效")
        if self.appliance:
            return await self._write_appliance(fields)
        fixed = fixed_air_volume(
            self.profile, fields.get("runM", self._status.get("runM"))
        )
        if "airVo" in fields:
            if (
                time.monotonic() < self._fixed_speed_pending_until
                and "runM" not in fields
            ):
                raise AirVolumeLockedError
            if fixed is not None:
                if "runM" not in fields or fields["airVo"] != fixed:
                    raise AirVolumeLockedError
                fields = {key: value for key, value in fields.items() if key != "airVo"}
        protocol = self.erv
        if not protocol or not fields or not fields.keys() <= protocol.writable_fields:
            raise CloudError("该设备协议或控制字段尚未匹配")
        if protocol.info_format and protocol.experimental:
            if not self._status or self._status.get("offline") in (1, "1"):
                raise CloudError("设备未连接或尚未取得有效状态")
            supported = {
                "runSta": {0, 1},
                "runM": set(protocol.mode_writes.values()),
                "airVo": protocol.speeds,
            }
            if any(
                value not in supported.get(key, ()) for key, value in fields.items()
            ):
                raise CloudError("该型号尚未支持请求中的控制值")
        last_error: str | None = None
        for attempt in range(MAX_SET_RETRIES):
            self._request_id += 1
            response = await self._post_set(fields)
            if auth_expired(response):
                await self.session_manager.relogin()
                continue
            if response.get("error") or (
                response_failed(response) and _extract_error_code(response) != "0"
            ):
                last_error = "松下云未确认控制请求"
                if attempt < MAX_SET_RETRIES - 1:
                    await asyncio.sleep(2**attempt + random.uniform(0, 0.5))
                    continue
                raise CloudError(last_error)
            if "runM" in fields:
                self._fixed_speed_pending_until = (
                    time.monotonic() + MODE_READBACK_GRACE if fixed is not None else 0.0
                )
            return response
        raise CloudError(last_error or "Panasonic set request failed after retries")

    async def _post_set(self, fields: dict[str, int]) -> dict[str, Any]:
        protocol = self.erv
        identity = self._identity()
        values = {
            key: self._status[key]
            for key in protocol.carry_status_keys
            if key in self._status
        }
        values.update(fields)
        params = protocol.payload_builder(
            self.device_id, self.token, identity["usrId"], **values
        )
        payload = protocol.write_body(self._request_id, identity, params)
        return await self._post(
            protocol.write_url,
            payload,
            xtoken=protocol.info_format,
            referer=protocol.referer,
        )

    async def _post(
        self,
        url: str,
        payload: dict,
        *,
        xtoken: bool = False,
        referer: str | None = None,
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        http = async_get_clientsession(self.hass)
        cookie = f"SSID={self.session_manager.session_id}"
        headers = {**HEADERS, "Cookie": cookie}
        if xtoken:
            headers["xtoken"] = cookie
        if referer:
            headers["Referer"] = (
                f"https://app.psmartcloud.com/ca/cn/{referer}/index.html"
            )
            headers["Origin"] = "https://app.psmartcloud.com"
            headers["X-Requested-With"] = "XMLHttpRequest"
        async with asyncio.timeout(10):
            async with http.post(
                url,
                json=payload,
                headers=headers,
                ssl=CLOUD_TLS,
                allow_redirects=False,
            ) as response:
                try:
                    data = await response.json()
                except (aiohttp.ContentTypeError, ValueError) as err:
                    if allow_empty and response.ok and not await response.read():
                        return {"errorCode": 0}
                    raise CloudError("松下云返回了无效响应") from err
                if not auth_expired(data):
                    response.raise_for_status()
                if data is None and allow_empty and not await response.read():
                    return {"errorCode": 0}
        if not isinstance(data, dict):
            raise CloudError("松下云返回了无效响应")
        return data
