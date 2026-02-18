"""Tests for hardware_agent.devices.visa_device — VisaDevice hint merging, detection, etc."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from hardware_agent.devices.base import DeviceDataSchema, DeviceHints, DeviceInfo
from hardware_agent.devices.visa_device import VisaDevice, _deep_merge


# ---------------------------------------------------------------------------
# Concrete test subclass (VisaDevice has ClassVars that need values)
# ---------------------------------------------------------------------------


class _TestVisaDevice(VisaDevice):
    """Concrete subclass with realistic class variables for testing."""

    VENDOR_ID: ClassVar[str] = "AAAA"
    PRODUCT_ID: ClassVar[str] = "BBBB"
    MODEL_PATTERNS: ClassVar[list[str]] = ["TestModel-100"]
    DEVICE_IDENTIFIER: ClassVar[str] = "test_visa_device"
    DEVICE_NAME: ClassVar[str] = "Test VISA Device"
    MANUFACTURER: ClassVar[str] = "TestCorp"
    CATEGORY: ClassVar[str] = "instrument"


class _TestVisaDeviceWithVendorHints(VisaDevice):
    """Subclass that provides vendor and device-specific hints for merge tests."""

    VENDOR_ID: ClassVar[str] = "1234"
    PRODUCT_ID: ClassVar[str] = "5678"
    MODEL_PATTERNS: ClassVar[list[str]] = ["MergeTest"]
    DEVICE_IDENTIFIER: ClassVar[str] = "merge_test_device"
    DEVICE_NAME: ClassVar[str] = "Merge Test Device"
    MANUFACTURER: ClassVar[str] = "MergeCorp"
    CATEGORY: ClassVar[str] = "test"

    def _get_vendor_hints(self, os: str) -> DeviceHints:
        return DeviceHints(
            common_errors={"VendorErr": "vendor fix"},
            setup_steps=["vendor step 1", "vendor step 2"],
            os_specific={},
            documentation_urls=["https://vendor.example.com"],
            known_quirks=["vendor quirk"],
            required_packages=["vendor-pkg"],
        )

    def _get_device_specific_hints(self, os: str) -> DeviceHints:
        return DeviceHints(
            common_errors={"DeviceErr": "device fix"},
            setup_steps=["device step 1"],
            os_specific={},
            documentation_urls=["https://device.example.com"],
            known_quirks=["device quirk"],
            required_packages=["device-pkg"],
        )

    def _get_device_specific_quirks(self) -> list[str]:
        return ["extra device quirk"]


# ---------------------------------------------------------------------------
# get_info
# ---------------------------------------------------------------------------


class TestGetInfo:
    def test_returns_device_info(self):
        device = _TestVisaDevice()
        info = device.get_info()
        assert isinstance(info, DeviceInfo)
        assert info.identifier == "test_visa_device"
        assert info.name == "Test VISA Device"
        assert info.manufacturer == "TestCorp"
        assert info.category == "instrument"
        assert info.model_patterns == ["TestModel-100"]
        assert info.connection_type == "visa"

    def test_model_patterns_is_copy(self):
        """get_info returns a list copy, not the class variable itself."""
        device = _TestVisaDevice()
        info = device.get_info()
        info.model_patterns.append("extra")
        assert "extra" not in _TestVisaDevice.MODEL_PATTERNS


# ---------------------------------------------------------------------------
# Hint merging
# ---------------------------------------------------------------------------


class TestHintMerging:
    """Verify that shared, vendor, and device-specific hints merge correctly."""

    def setup_method(self):
        self.device = _TestVisaDeviceWithVendorHints()

    def test_common_errors_merged(self):
        hints = self.device.get_hints("linux")
        # Shared VISA errors should be present
        assert "No backend available" in hints.common_errors
        # Vendor-specific error should be present
        assert "VendorErr" in hints.common_errors
        # Device-specific error should be present
        assert "DeviceErr" in hints.common_errors

    def test_device_errors_override_shared(self):
        """If the same key appears in multiple layers, later layers win."""

        class OverrideDevice(VisaDevice):
            VENDOR_ID: ClassVar[str] = "0000"
            PRODUCT_ID: ClassVar[str] = "0000"
            MODEL_PATTERNS: ClassVar[list[str]] = []
            DEVICE_IDENTIFIER: ClassVar[str] = "override"
            DEVICE_NAME: ClassVar[str] = "Override"
            MANUFACTURER: ClassVar[str] = "X"
            CATEGORY: ClassVar[str] = "x"

            def _get_device_specific_hints(self, os: str) -> DeviceHints:
                return DeviceHints(
                    common_errors={
                        "No backend available": "DEVICE-LEVEL FIX",
                    }
                )

        device = OverrideDevice()
        hints = device.get_hints("linux")
        assert hints.common_errors["No backend available"] == "DEVICE-LEVEL FIX"

    def test_setup_steps_most_specific_wins(self):
        """setup_steps uses the most specific non-empty list (device > vendor > shared)."""
        hints = self.device.get_hints("linux")
        # Device has setup_steps ["device step 1"], so it should win.
        assert hints.setup_steps == ["device step 1"]

    def test_setup_steps_falls_back_to_vendor(self):
        """When device has no setup_steps, vendor steps are used."""

        class NoDeviceSteps(VisaDevice):
            VENDOR_ID: ClassVar[str] = "0000"
            PRODUCT_ID: ClassVar[str] = "0000"
            MODEL_PATTERNS: ClassVar[list[str]] = []
            DEVICE_IDENTIFIER: ClassVar[str] = "nds"
            DEVICE_NAME: ClassVar[str] = "NDS"
            MANUFACTURER: ClassVar[str] = "X"
            CATEGORY: ClassVar[str] = "x"

            def _get_vendor_hints(self, os: str) -> DeviceHints:
                return DeviceHints(setup_steps=["vendor step"])

        device = NoDeviceSteps()
        hints = device.get_hints("linux")
        assert hints.setup_steps == ["vendor step"]

    def test_setup_steps_falls_back_to_shared(self):
        """When neither device nor vendor provide steps, shared steps are used."""
        device = _TestVisaDevice()  # no vendor/device hint overrides
        hints = device.get_hints("linux")
        # Should get the shared VISA setup steps
        assert len(hints.setup_steps) > 0
        assert "Install pyvisa" in hints.setup_steps[0]

    def test_known_quirks_concatenated_and_deduplicated(self):
        hints = self.device.get_hints("linux")
        assert "vendor quirk" in hints.known_quirks
        assert "extra device quirk" in hints.known_quirks
        assert "device quirk" in hints.known_quirks
        # No duplicates
        assert len(hints.known_quirks) == len(set(hints.known_quirks))

    def test_required_packages_union(self):
        hints = self.device.get_hints("linux")
        # Shared packages
        assert "pyvisa" in hints.required_packages
        assert "pyvisa-py" in hints.required_packages
        assert "pyusb" in hints.required_packages
        # Vendor package
        assert "vendor-pkg" in hints.required_packages
        # Device package
        assert "device-pkg" in hints.required_packages

    def test_documentation_urls_concatenated(self):
        hints = self.device.get_hints("linux")
        assert "https://vendor.example.com" in hints.documentation_urls
        assert "https://device.example.com" in hints.documentation_urls

    def test_os_specific_linux(self):
        hints = self.device.get_hints("linux")
        assert "linux" in hints.os_specific
        assert "udev_rule" in hints.os_specific["linux"]

    def test_os_specific_windows(self):
        hints = self.device.get_hints("windows")
        assert "windows" in hints.os_specific

    def test_os_specific_macos(self):
        hints = self.device.get_hints("macos")
        assert "macos" in hints.os_specific


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------


class TestDetect:
    def setup_method(self):
        self.device = _TestVisaDevice()

    def test_detect_matching_usb_device(self):
        usb_devices = ["Bus 001 Device 005: ID aaaa:bbbb TestCorp Device"]
        assert self.device.detect(usb_devices, []) is True

    def test_detect_matching_usb_case_insensitive(self):
        usb_devices = ["Bus 001 Device 005: ID AAAA:BBBB TestCorp Device"]
        assert self.device.detect(usb_devices, []) is True

    def test_detect_non_matching_usb_device(self):
        usb_devices = ["Bus 001 Device 005: ID ffff:0000 OtherCorp Device"]
        assert self.device.detect(usb_devices, []) is False

    def test_detect_matching_visa_resource(self):
        visa_resources = ["USB0::AAAA::BBBB::12345678::INSTR"]
        assert self.device.detect([], visa_resources) is True

    def test_detect_non_matching_visa_resource(self):
        visa_resources = ["USB0::0xFFFF::0x0000::12345678::INSTR"]
        assert self.device.detect([], visa_resources) is False

    def test_detect_empty_lists(self):
        assert self.device.detect([], []) is False

    def test_detect_usb_matches_before_visa_checked(self):
        """If USB matches, VISA resources are not needed."""
        usb = ["Bus 001 Device 005: ID aaaa:9999 Something"]
        visa = []
        assert self.device.detect(usb, visa) is True


# ---------------------------------------------------------------------------
# verify_connection (mocked _run_python)
# ---------------------------------------------------------------------------


class TestVerifyConnection:
    def setup_method(self):
        self.device = _TestVisaDevice()

    @patch.object(_TestVisaDevice, "_run_python")
    def test_verify_success(self, mock_run):
        mock_run.return_value = (True, "TestCorp,TestModel-100,SN123,1.0.0")
        success, output = self.device.verify_connection()
        assert success is True
        assert "TestModel-100" in output
        mock_run.assert_called_once()
        # The code passed to _run_python should reference the device IDs
        code_arg = mock_run.call_args[0][0]
        assert "AAAA" in code_arg
        assert "BBBB" in code_arg

    @patch.object(_TestVisaDevice, "_run_python")
    def test_verify_failure(self, mock_run):
        mock_run.return_value = (False, "ERROR: No VISA resource found")
        success, output = self.device.verify_connection()
        assert success is False
        assert "No VISA resource found" in output


# ---------------------------------------------------------------------------
# generate_example_code
# ---------------------------------------------------------------------------


class TestGenerateExampleCode:
    def test_contains_vendor_id(self):
        device = _TestVisaDevice()
        code = device.generate_example_code()
        assert "AAAA" in code

    def test_contains_device_name(self):
        device = _TestVisaDevice()
        code = device.generate_example_code()
        assert "Test VISA Device" in code

    def test_non_empty(self):
        device = _TestVisaDevice()
        assert len(device.generate_example_code()) > 0


# ---------------------------------------------------------------------------
# get_data_schema
# ---------------------------------------------------------------------------


class TestGetDataSchema:
    def test_base_visa_schema(self):
        device = _TestVisaDevice()
        schema = device.get_data_schema()
        assert isinstance(schema, DeviceDataSchema)
        assert "firmware_version" in schema.fields
        assert "serial_number" in schema.fields


# ---------------------------------------------------------------------------
# _deep_merge helper
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_simple_merge(self):
        result = _deep_merge({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_later_values_win(self):
        result = _deep_merge({"a": 1}, {"a": 2})
        assert result == {"a": 2}

    def test_nested_merge(self):
        result = _deep_merge(
            {"os": {"linux": {"key1": "v1"}}},
            {"os": {"linux": {"key2": "v2"}}},
        )
        assert result == {"os": {"linux": {"key1": "v1", "key2": "v2"}}}

    def test_three_dicts(self):
        result = _deep_merge({"a": 1}, {"b": 2}, {"c": 3})
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_empty_dicts(self):
        result = _deep_merge({}, {}, {})
        assert result == {}
