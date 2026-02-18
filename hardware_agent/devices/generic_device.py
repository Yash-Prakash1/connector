"""Tier 2: GenericDevice — fallback for devices without a protocol layer."""

from __future__ import annotations

from hardware_agent.devices.base import (
    DeviceDataSchema,
    DeviceHints,
    DeviceInfo,
    DeviceModule,
)


class GenericDevice(DeviceModule):
    """Fallback base class for devices that don't fit VISA or any other protocol layer."""

    DEVICE_IDENTIFIER: str = ""
    DEVICE_NAME: str = ""
    MANUFACTURER: str = ""
    CATEGORY: str = ""
    CONNECTION_TYPE: str = "generic"

    def get_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifier=self.DEVICE_IDENTIFIER,
            name=self.DEVICE_NAME,
            manufacturer=self.MANUFACTURER,
            category=self.CATEGORY,
            model_patterns=[],
            connection_type=self.CONNECTION_TYPE,
        )

    def get_hints(self, os: str) -> DeviceHints:
        return DeviceHints(
            common_errors={},
            setup_steps=["Refer to device documentation"],
            os_specific={},
            documentation_urls=[],
            known_quirks=[],
            required_packages=[],
        )

    def detect(self, usb_devices: list[str], visa_resources: list[str]) -> bool:
        return False

    def verify_connection(self) -> tuple[bool, str]:
        return False, "Manual verification required for this device type"

    def generate_example_code(self) -> str:
        return "# No example code available for this device type"

    def get_data_schema(self) -> DeviceDataSchema:
        return DeviceDataSchema()
