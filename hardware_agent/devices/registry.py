"""Device registry — auto-discovers device modules from subdirectories."""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path
from typing import Optional

from hardware_agent.devices.base import DeviceModule
from hardware_agent.devices.generic_device import GenericDevice
from hardware_agent.devices.visa_device import VisaDevice

logger = logging.getLogger(__name__)

# Base classes that should not be registered as devices
_BASE_CLASSES = {DeviceModule, VisaDevice, GenericDevice}

_registry: dict[str, DeviceModule] = {}
_discovered = False


def _discover() -> None:
    """Walk hardware_agent/devices/ subdirectories and register device modules."""
    global _discovered
    if _discovered:
        return

    devices_dir = Path(__file__).parent
    for child in sorted(devices_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_"):
            continue
        module_file = child / "module.py"
        if not module_file.exists():
            continue

        module_path = f"hardware_agent.devices.{child.name}.module"
        try:
            mod = importlib.import_module(module_path)
        except Exception:
            logger.warning("Failed to import %s", module_path, exc_info=True)
            continue

        for _name, obj in inspect.getmembers(mod, inspect.isclass):
            if not issubclass(obj, DeviceModule):
                continue
            if obj in _BASE_CLASSES:
                continue
            if inspect.isabstract(obj):
                continue
            try:
                instance = obj()
                info = instance.get_info()
                _registry[info.identifier] = instance
            except Exception:
                logger.warning(
                    "Failed to instantiate %s from %s", _name, module_path,
                    exc_info=True,
                )

    _discovered = True


def list_modules() -> list[str]:
    """Return identifiers of all registered device modules."""
    _discover()
    return list(_registry.keys())


def get_module(identifier: str) -> DeviceModule:
    """Return a device module by identifier, or raise ValueError."""
    _discover()
    if identifier not in _registry:
        available = ", ".join(_registry.keys()) or "(none)"
        raise ValueError(
            f"Unknown device: {identifier!r}. Available: {available}"
        )
    return _registry[identifier]


def detect_device(
    usb_devices: list[str], visa_resources: list[str]
) -> Optional[DeviceModule]:
    """Try all modules and return the first that detects a connected device."""
    _discover()
    for module in _registry.values():
        try:
            if module.detect(usb_devices, visa_resources):
                return module
        except Exception:
            logger.debug(
                "Detection failed for %s", module.get_info().identifier,
                exc_info=True,
            )
    return None


def _reset() -> None:
    """Reset registry state. For testing only."""
    global _discovered
    _registry.clear()
    _discovered = False
