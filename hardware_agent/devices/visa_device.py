"""Tier 2: VisaDevice — shared VISA/SCPI logic for all VISA instruments."""

from __future__ import annotations

import re
from typing import ClassVar

from hardware_agent.devices.base import (
    DeviceDataSchema,
    DeviceHints,
    DeviceInfo,
    DeviceModule,
)


class VisaDevice(DeviceModule):
    """Base class for all VISA/SCPI instruments.

    Subclasses set class attributes and override hooks.
    """

    VENDOR_ID: ClassVar[str] = ""
    PRODUCT_ID: ClassVar[str] = ""
    MODEL_PATTERNS: ClassVar[list[str]] = []
    DEVICE_IDENTIFIER: ClassVar[str] = ""
    DEVICE_NAME: ClassVar[str] = ""
    MANUFACTURER: ClassVar[str] = ""
    CATEGORY: ClassVar[str] = ""

    # ── Tier 1 concrete implementations ──────────────────────────────

    def get_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifier=self.DEVICE_IDENTIFIER,
            name=self.DEVICE_NAME,
            manufacturer=self.MANUFACTURER,
            category=self.CATEGORY,
            model_patterns=list(self.MODEL_PATTERNS),
            connection_type="visa",
        )

    def get_hints(self, os: str) -> DeviceHints:
        shared = self._get_shared_visa_hints(os)
        vendor = self._get_vendor_hints(os)
        device = self._get_device_specific_hints(os)

        # Merge: device > vendor > shared
        common_errors = {
            **shared.common_errors,
            **vendor.common_errors,
            **device.common_errors,
        }

        # setup_steps: most specific non-empty list
        setup_steps = (
            device.setup_steps
            or vendor.setup_steps
            or shared.setup_steps
        )

        # os_specific: deep merge
        os_specific = _deep_merge(
            shared.os_specific, vendor.os_specific, device.os_specific
        )

        # known_quirks: concatenate, deduplicated
        all_quirks = shared.known_quirks + vendor.known_quirks
        all_quirks += self._get_device_specific_quirks()
        all_quirks += device.known_quirks
        known_quirks = list(dict.fromkeys(all_quirks))

        # required_packages: union
        required_packages = list(dict.fromkeys(
            shared.required_packages
            + vendor.required_packages
            + device.required_packages
        ))

        # documentation_urls: concatenate
        documentation_urls = list(dict.fromkeys(
            shared.documentation_urls
            + vendor.documentation_urls
            + device.documentation_urls
        ))

        return DeviceHints(
            common_errors=common_errors,
            setup_steps=setup_steps,
            os_specific=os_specific,
            documentation_urls=documentation_urls,
            known_quirks=known_quirks,
            required_packages=required_packages,
        )

    def detect(self, usb_devices: list[str], visa_resources: list[str]) -> bool:
        vid = self.VENDOR_ID.lower()
        for dev in usb_devices:
            if vid in dev.lower():
                return True
        pattern = re.compile(
            rf"USB.*::{self.VENDOR_ID}::{self.PRODUCT_ID}::.*", re.IGNORECASE
        )
        for res in visa_resources:
            if pattern.search(res):
                return True
        return False

    def verify_connection(self) -> tuple[bool, str]:
        code = f"""\
import pyvisa
rm = pyvisa.ResourceManager('@py')
resources = rm.list_resources()
pattern = "{self.VENDOR_ID}.*{self.PRODUCT_ID}"
import re
matched = [r for r in resources if re.search(pattern, r, re.IGNORECASE)]
if not matched:
    print("ERROR: No VISA resource found matching vendor={self.VENDOR_ID} product={self.PRODUCT_ID}")
    raise SystemExit(1)
inst = rm.open_resource(matched[0])
idn = inst.query("*IDN?").strip()
inst.close()
print(idn)
"""
        return self._run_python(code)

    def generate_example_code(self) -> str:
        return f"""\
import pyvisa

rm = pyvisa.ResourceManager('@py')
resources = rm.list_resources()
print("Available VISA resources:", resources)

# Connect to {self.DEVICE_NAME}
# Look for resource containing vendor ID {self.VENDOR_ID}
import re
matched = [r for r in resources if re.search(r"{self.VENDOR_ID}", r, re.IGNORECASE)]
if not matched:
    raise RuntimeError("Device not found. Check USB connection.")

inst = rm.open_resource(matched[0])
print("Connected to:", inst.query("*IDN?").strip())
inst.close()
"""

    def get_data_schema(self) -> DeviceDataSchema:
        return DeviceDataSchema(fields={
            "firmware_version": "str",
            "serial_number": "str",
        })

    # ── Shared VISA hints ────────────────────────────────────────────

    def _get_shared_visa_hints(self, os: str) -> DeviceHints:
        common_errors = {
            "No backend available": "Install pyvisa-py: pip install pyvisa-py",
            "No module named 'usb'": "Install pyusb: pip install pyusb",
            "No module named 'usb.core'": (
                "Install libusb system package (apt install libusb-1.0-0-dev "
                "or brew install libusb)"
            ),
            "Resource busy": "Close other software using the device",
            "VI_ERROR_RSRC_NFOUND": "Device not found — check USB connection",
            "Permission denied": "USB permissions issue — see setup steps",
            "[Errno 13]": "USB permissions issue — see setup steps",
            "Timeout": "Try a different USB port or check device power",
        }

        setup_steps = [
            "Install pyvisa: pip install pyvisa",
            "Install pyvisa-py backend: pip install pyvisa-py",
            "Install USB library: pip install pyusb",
            "Install system libusb",
            "Fix USB permissions (Linux: udev rule, Windows: Zadig driver)",
            "Detect device with list_usb_devices / list_visa_resources",
            "Test communication with *IDN? query",
        ]

        required_packages = ["pyvisa", "pyvisa-py", "pyusb"]

        os_specific: dict[str, dict] = {}
        vid = self.VENDOR_ID.lower()
        if os == "linux":
            os_specific["linux"] = {
                "udev_rule": (
                    f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vid}", MODE="0666"'
                ),
                "udev_file": f"/etc/udev/rules.d/99-{self.MANUFACTURER.lower()}.rules",
                "udev_reload": (
                    "sudo udevadm control --reload-rules && sudo udevadm trigger"
                ),
                "libusb_install": "sudo apt install libusb-1.0-0-dev",
            }
        elif os == "macos":
            os_specific["macos"] = {
                "libusb_install": "brew install libusb",
            }
        elif os == "windows":
            os_specific["windows"] = {
                "driver_note": (
                    "Install NI-VISA or use Zadig to install WinUSB driver"
                ),
            }

        return DeviceHints(
            common_errors=common_errors,
            setup_steps=setup_steps,
            os_specific=os_specific,
            documentation_urls=[],
            known_quirks=[],
            required_packages=required_packages,
        )

    # ── Hooks for Tier 3 subclasses ──────────────────────────────────

    def _get_device_specific_hints(self, os: str) -> DeviceHints:
        return DeviceHints()

    def _get_device_specific_quirks(self) -> list[str]:
        return []

    def _get_vendor_hints(self, os: str) -> DeviceHints:
        return DeviceHints()


def _deep_merge(*dicts: dict) -> dict:
    """Merge multiple dicts recursively. Later values win."""
    result: dict = {}
    for d in dicts:
        for key, value in d.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = _deep_merge(result[key], value)
            else:
                result[key] = value
    return result
