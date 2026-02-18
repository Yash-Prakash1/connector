"""Fingerprinting — hashes initial state for pattern matching."""

from __future__ import annotations

import hashlib
import json

from hardware_agent.core.models import Environment


RELEVANT_PACKAGES = ["pyvisa", "pyvisa-py", "pyusb", "pyserial"]


def fingerprint_initial_state(env: Environment, device_type: str) -> str:
    """Create a hash of the relevant initial state.

    Same fingerprint = same starting point = same recipe should work.
    """
    state = {
        "device": device_type,
        "os": env.os.value,
        "packages": {
            p: env.installed_packages.get(p) for p in RELEVANT_PACKAGES
        },
        "device_visible_usb": _any_matching_usb_device(env, device_type),
        "visa_available": len(env.visa_resources) > 0,
    }
    serialized = json.dumps(state, sort_keys=True).encode()
    return hashlib.sha256(serialized).hexdigest()[:16]


def _any_matching_usb_device(env: Environment, device_type: str) -> bool:
    """Check if any USB device might match this device type."""
    # Map device types to vendor IDs to look for
    vendor_ids = {
        "rigol_ds1054z": "1ab1",
        "rigol_dp832": "1ab1",
        "rigol_dl3021": "1ab1",
        "rigol_m300": "1ab1",
    }
    vid = vendor_ids.get(device_type, "")
    if not vid:
        return False
    return any(vid in dev.lower() for dev in env.usb_devices)
