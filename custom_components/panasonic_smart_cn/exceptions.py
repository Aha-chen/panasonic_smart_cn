"""Exceptions for Panasonic Fresh Air CN."""

from __future__ import annotations


class PanasonicFreshAirError(Exception):
    """Base exception."""


class AuthenticationError(PanasonicFreshAirError):
    """Authentication failed or session expired."""


class CloudError(PanasonicFreshAirError):
    """Panasonic cloud returned an error."""


class AirVolumeLockedError(PanasonicFreshAirError):
    """The current mode determines the air volume."""


class ControlNotConfirmedError(PanasonicFreshAirError):
    """The cloud accepted the command, but readback did not confirm it."""


class UnsupportedDeviceError(PanasonicFreshAirError):
    """The selected device is not supported by this integration."""
