"""Module loader — thin wrapper around device registry for the orchestrator/CLI."""

from __future__ import annotations

from typing import Optional

from hardware_agent.core.models import Environment
from hardware_agent.devices import registry
from hardware_agent.devices.base import DeviceModule


def list_available_modules() -> list[str]:
    """List identifiers of all available device modules."""
    return registry.list_modules()


def load_module(identifier: str) -> DeviceModule:
    """Load a device module by identifier. Raises ValueError if unknown."""
    return registry.get_module(identifier)


def auto_detect_device(environment: Environment) -> Optional[DeviceModule]:
    """Try to auto-detect a connected device from environment data."""
    return registry.detect_device(
        environment.usb_devices, environment.visa_resources
    )
