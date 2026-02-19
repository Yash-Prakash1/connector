"""Null-object DeviceModule for troubleshoot mode without a specific device."""

from __future__ import annotations

from hardware_agent.devices.base import (
    DeviceDataSchema,
    DeviceHints,
    DeviceInfo,
    DeviceModule,
)


class NullDeviceModule(DeviceModule):
    """Stub device for when no specific device is selected."""

    def get_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifier="unknown",
            name="Unknown / Not specified",
            manufacturer="",
            category="",
            model_patterns=[],
            connection_type="unknown",
        )

    def get_hints(self, os: str) -> DeviceHints:
        return DeviceHints()

    def detect(self, usb_devices: list[str], visa_resources: list[str]) -> bool:
        return False

    def verify_connection(self) -> tuple[bool, str]:
        return False, "No device configured — troubleshoot mode"

    def generate_example_code(self) -> str:
        return ""

    def get_data_schema(self) -> DeviceDataSchema:
        return DeviceDataSchema()
