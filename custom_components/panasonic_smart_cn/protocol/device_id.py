"""Device ID parsing and token generation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..const import FRESH_AIR_CATEGORIES


@dataclass(frozen=True)
class ParsedDeviceId:
    """Parsed Panasonic device id."""

    raw: str
    mac: str
    category: str
    suffix: str

    @property
    def is_fresh_air(self) -> bool:
        """Return whether the category is a known fresh-air category."""
        return self.category in FRESH_AIR_CATEGORIES


def parse_device_id(device_id: str) -> ParsedDeviceId | None:
    """Parse MAC_CATEGORY_SUFFIX device ids used by Panasonic Smart China."""
    parts = device_id.split("_")
    if len(parts) != 3:
        return None
    mac, category, suffix = parts
    if len(mac) < 12:
        return None
    return ParsedDeviceId(
        raw=device_id,
        mac=mac.upper(),
        category=category.upper(),
        suffix=suffix,
    )


def generate_device_token(device_id: str) -> str | None:
    """Generate the per-device control token.

    The algorithm is derived from Panasonic Smart China app behavior:
    sha512(sha512(mac_tail + "_" + category + "_" + mac_head) + "_" + suffix).
    The suffix is intentionally kept case-sensitive.
    """
    parsed = parse_device_id(device_id)
    if parsed is None:
        return None
    seed = f"{parsed.mac[6:]}_{parsed.category}_{parsed.mac[:6]}"
    inner = hashlib.sha512(seed.encode()).hexdigest()
    return hashlib.sha512(f"{inner}_{parsed.suffix}".encode()).hexdigest()
