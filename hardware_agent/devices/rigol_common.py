"""Vendor common hints shared across all Rigol devices."""

from __future__ import annotations

from hardware_agent.devices.base import DeviceHints

RIGOL_VENDOR_ID = "1AB1"


def get_rigol_common_hints(os: str) -> DeviceHints:
    """Return hints shared by all Rigol instruments."""
    common_errors: dict[str, str] = {
        "Resource busy": (
            "Close Rigol Ultra Sigma software — it claims the USB device exclusively"
        ),
    }

    known_quirks = [
        "Rigol Ultra Sigma may claim the USB device — close it before connecting",
        "Some Rigol firmware versions respond slowly to first *IDN? query",
        "Rigol USB devices use vendor ID 0x1AB1",
    ]

    os_specific: dict[str, dict] = {}
    if os == "linux":
        os_specific["linux"] = {
            "udev_rule": (
                'SUBSYSTEM=="usb", ATTR{idVendor}=="1ab1", MODE="0666"'
            ),
            "udev_file": "/etc/udev/rules.d/99-rigol.rules",
            "udev_reload": (
                "sudo udevadm control --reload-rules && sudo udevadm trigger"
            ),
        }

    return DeviceHints(
        common_errors=common_errors,
        setup_steps=[],
        os_specific=os_specific,
        documentation_urls=["https://www.rigol.com/"],
        known_quirks=known_quirks,
        required_packages=[],
    )
