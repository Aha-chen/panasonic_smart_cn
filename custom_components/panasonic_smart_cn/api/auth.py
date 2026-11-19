"""Authentication primitives for Panasonic Smart China."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any

import aiohttp

from ..const import AUTH_EXPIRED_CODES, URL_GET_DEVICES, URL_GET_TOKEN, URL_LOGIN
from ..exceptions import AuthenticationError, CloudError

HEADERS = {"User-Agent": "SmartApp", "Content-Type": "application/json"}
# The Panasonic endpoint uses a self-signed certificate. Verify that exact
# certificate before sending cloud credentials or a session cookie.
CLOUD_TLS = aiohttp.Fingerprint(
    bytes.fromhex("a03226da8dd2ef0ea7e390232eed88d27d36c9e1a3208439f20a4c37eec35948")
)


@dataclass(frozen=True)
class PanasonicSession:
    """Authenticated Panasonic Smart China session."""

    username: str
    user_id: str
    session_id: str
    family_id: Any
    real_family_id: Any
    devices: dict[str, dict[str, Any]]


def hash_password(username: str, password: str, token_start: str) -> str:
    """Generate the login digest used by Panasonic Smart China."""
    password_md5 = hashlib.md5(password.encode()).hexdigest().upper()
    intermediate = hashlib.md5(f"{password_md5}{username}".encode()).hexdigest().upper()
    return hashlib.md5(f"{intermediate}{token_start}".encode()).hexdigest().upper()


def make_client_id(seed: str) -> str:
    """Create a stable locally-administered MAC-like telId for HA.

    The official app sends a device identifier as telId. Using a fixed all-zero
    telId makes every HA install look like the same client device. A stable,
    locally-administered MAC-like value gives the cloud a better chance to keep
    HA separate from the user's phone session when it keys sessions by client.
    """
    digest = hashlib.sha256(seed.encode()).digest()
    octets = [0x02, *digest[:5]]
    return ":".join(f"{octet:02X}" for octet in octets)


async def authenticate(
    http: aiohttp.ClientSession,
    username: str,
    password: str,
    client_id: str | None = None,
) -> PanasonicSession:
    """Run GetToken -> Login -> GetBindDevInfo."""
    tel_id = client_id or make_client_id(username)
    async with asyncio.timeout(10):
        async with http.post(
            URL_GET_TOKEN,
            json={"id": 1, "uiVersion": 4.0, "params": {"usrId": username}},
            headers=HEADERS,
            ssl=CLOUD_TLS,
            allow_redirects=False,
        ) as response:
            token_data = await response.json()

    try:
        token_start = token_data["results"]["token"]
    except (KeyError, TypeError) as err:
        raise CloudError("无法获取松下登录凭据") from err

    digest = hash_password(username, password, token_start)
    async with asyncio.timeout(10):
        async with http.post(
            URL_LOGIN,
            json={
                "id": 2,
                "uiVersion": 4.0,
                "params": {
                    "telId": tel_id,
                    "checkFailCount": 0,
                    "usrId": username,
                    "pwd": digest,
                },
            },
            headers=HEADERS,
            ssl=CLOUD_TLS,
            allow_redirects=False,
        ) as response:
            login_data = await response.json()

    try:
        result = login_data["results"]
        user_id = result["usrId"]
        session_id = result["ssId"]
    except (KeyError, TypeError) as err:
        raise AuthenticationError("松下账号登录失败") from err

    family_id = result.get("familyId")
    real_family_id = result.get("realFamilyId")
    devices = await fetch_devices(http, user_id, session_id, family_id, real_family_id)
    return PanasonicSession(
        username=username,
        user_id=user_id,
        session_id=session_id,
        family_id=family_id,
        real_family_id=real_family_id,
        devices=devices,
    )


async def fetch_devices(
    http: aiohttp.ClientSession,
    user_id: str,
    session_id: str,
    family_id: Any,
    real_family_id: Any,
) -> dict[str, dict[str, Any]]:
    """Fetch bound devices and normalize them by device id."""
    async with asyncio.timeout(10):
        async with http.post(
            URL_GET_DEVICES,
            json={
                "id": 3,
                "uiVersion": 4.0,
                "params": {
                    "realFamilyId": real_family_id,
                    "familyId": family_id,
                    "usrId": user_id,
                },
            },
            headers={**HEADERS, "Cookie": f"SSID={session_id}"},
            ssl=CLOUD_TLS,
            allow_redirects=False,
        ) as response:
            data = await response.json()

    if isinstance(data, dict):
        error = data.get("error")
        code = data.get(
            "errorCode", error.get("code") if isinstance(error, dict) else None
        )
        if str(code) in AUTH_EXPIRED_CODES:
            raise AuthenticationError("松下登录会话已失效")
    try:
        entries = data["results"]["devList"]
    except (KeyError, TypeError) as err:
        raise CloudError("无法读取松下账号设备列表") from err
    if not isinstance(entries, list):
        raise CloudError("松下账号设备列表格式无效")
    devices: dict[str, dict[str, Any]] = {}
    for raw_device in entries:
        if not isinstance(raw_device, dict):
            continue
        device_id = raw_device.get("deviceId")
        if not isinstance(device_id, str) or not device_id:
            continue
        params = raw_device.get("params") or {}
        if not isinstance(params, dict):
            continue
        devices[device_id] = {
            "deviceName": raw_device.get("deviceName") or params.get("deviceName"),
            "params": params,
        }
    return devices
