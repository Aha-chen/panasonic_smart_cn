"""Resolve Panasonic device identities to the supported protocol definitions."""

from __future__ import annotations

from .appliances import match_appliance
from .device_id import parse_device_id
from .erv import ERV_PROTOCOLS
from .mappings import int_or_none

SUBTYPE_ALIASES = {"DCERV-03": "DCERV", "SMALLERV-02": "SMALLERV02"}
MODEL_PROFILES = {
    model: name for name, protocol in ERV_PROTOCOLS.items() for model in protocol.models
}


def hardware_validation_pending(profile: str | None, model: str | None) -> bool:
    """Only the LD6C control path on FV-35ZDP2C has local hardware evidence."""
    return profile is not None and (profile, str(model or "").strip().upper()) != (
        "LD6C",
        "FV-35ZDP2C",
    )


def profile_from_sub_type(subtype: str | None, model: str | None = None) -> str | None:
    """Resolve known protocol families and evidenced model aliases."""
    subtype = str(subtype or "").strip().upper()
    if subtype in ERV_PROTOCOLS:
        return subtype
    if subtype in SUBTYPE_ALIASES:
        return SUBTYPE_ALIASES[subtype]
    if not subtype or subtype in MODEL_PROFILES:
        return MODEL_PROFILES.get(subtype) or MODEL_PROFILES.get(
            str(model or "").strip().upper()
        )
    return None


def match_profile(device_id: str, subtype: str | None, model: str | None) -> str | None:
    """Match a category and explicit subtype or supported model."""
    parsed = parse_device_id(device_id)
    if parsed is None:
        return None
    if parsed.is_fresh_air:
        return profile_from_sub_type(subtype, model)
    return match_appliance(parsed, subtype, model)


def core_controls(profile: str | None) -> frozenset[str]:
    """Return only the controls wired for a known protocol."""
    if protocol := ERV_PROTOCOLS.get(profile):
        return protocol.writable_fields
    return frozenset()


def fixed_air_volume(profile: str | None, run_mode: int | str | None) -> int | None:
    """Return the forced speed for an evidenced mode-level restriction."""
    if protocol := ERV_PROTOCOLS.get(profile):
        return protocol.fixed_speeds.get(int_or_none(run_mode))
    return None


def display_options(
    profile: str,
) -> tuple[dict[int, str], dict[str, int], dict[int, str]]:
    """Map cloud values to the app's running-mode and speed labels."""
    protocol = ERV_PROTOCOLS[profile]
    return protocol.modes, protocol.mode_writes, protocol.speeds
