"""Tests for hardware_agent.devices.rigol_ds1054z.module — RigolDS1054ZModule."""

from __future__ import annotations

import pytest

from hardware_agent.devices.base import DeviceDataSchema, DeviceHints, DeviceInfo
from hardware_agent.devices.rigol_ds1054z.module import RigolDS1054ZModule


@pytest.fixture
def rigol() -> RigolDS1054ZModule:
    return RigolDS1054ZModule()


# ---------------------------------------------------------------------------
# get_info
# ---------------------------------------------------------------------------


class TestGetInfo:
    def test_identifier(self, rigol):
        info = rigol.get_info()
        assert info.identifier == "rigol_ds1054z"

    def test_name(self, rigol):
        assert rigol.get_info().name == "Rigol DS1054Z"

    def test_manufacturer(self, rigol):
        assert rigol.get_info().manufacturer == "Rigol"

    def test_category(self, rigol):
        assert rigol.get_info().category == "oscilloscope"

    def test_connection_type(self, rigol):
        assert rigol.get_info().connection_type == "visa"

    def test_model_patterns(self, rigol):
        patterns = rigol.get_info().model_patterns
        assert "DS1054Z" in patterns
        assert "DS1074Z" in patterns
        assert "DS1104Z" in patterns
        assert "DS1202Z" in patterns

    def test_returns_device_info_instance(self, rigol):
        assert isinstance(rigol.get_info(), DeviceInfo)


# ---------------------------------------------------------------------------
# get_hints — three-layer merge (shared VISA + Rigol vendor + DS1054Z device)
# ---------------------------------------------------------------------------


class TestGetHints:
    def test_returns_device_hints_instance(self, rigol):
        hints = rigol.get_hints("linux")
        assert isinstance(hints, DeviceHints)

    # -- Shared VISA layer --

    def test_shared_visa_error_present(self, rigol):
        hints = rigol.get_hints("linux")
        assert "No backend available" in hints.common_errors

    def test_shared_visa_packages(self, rigol):
        hints = rigol.get_hints("linux")
        assert "pyvisa" in hints.required_packages
        assert "pyvisa-py" in hints.required_packages
        assert "pyusb" in hints.required_packages

    # -- Rigol vendor layer --

    def test_rigol_vendor_error_present(self, rigol):
        hints = rigol.get_hints("linux")
        # Rigol common overrides "Resource busy" with Rigol-specific message
        assert "Resource busy" in hints.common_errors
        assert "Ultra Sigma" in hints.common_errors["Resource busy"]

    def test_rigol_vendor_quirks_present(self, rigol):
        hints = rigol.get_hints("linux")
        rigol_quirk_found = any("1AB1" in q for q in hints.known_quirks)
        assert rigol_quirk_found, "Expected Rigol vendor ID quirk"

    def test_rigol_documentation_url(self, rigol):
        hints = rigol.get_hints("linux")
        assert any("rigol.com" in url for url in hints.documentation_urls)

    # -- DS1054Z device layer --

    def test_device_specific_quirks_present(self, rigol):
        hints = rigol.get_hints("linux")
        assert any("USB 3.0" in q for q in hints.known_quirks)
        assert any("TMC header" in q for q in hints.known_quirks)
        assert any("VXI-11" in q or "LAN" in q for q in hints.known_quirks)

    def test_quirks_deduplicated(self, rigol):
        hints = rigol.get_hints("linux")
        assert len(hints.known_quirks) == len(set(hints.known_quirks))

    # -- OS-specific hints --

    def test_linux_os_specific_has_udev(self, rigol):
        hints = rigol.get_hints("linux")
        assert "linux" in hints.os_specific
        linux_info = hints.os_specific["linux"]
        assert "udev_rule" in linux_info
        # Rigol vendor udev rule should mention 1ab1
        assert "1ab1" in linux_info["udev_rule"]

    def test_windows_os_specific(self, rigol):
        hints = rigol.get_hints("windows")
        assert "windows" in hints.os_specific

    def test_macos_os_specific(self, rigol):
        hints = rigol.get_hints("macos")
        assert "macos" in hints.os_specific


# ---------------------------------------------------------------------------
# detect
# ---------------------------------------------------------------------------


class TestDetect:
    def test_detect_with_rigol_usb_string(self, rigol):
        usb = ["Bus 001 Device 003: ID 1ab1:04ce Rigol Technologies DS1054Z"]
        assert rigol.detect(usb, []) is True

    def test_detect_with_rigol_usb_uppercase(self, rigol):
        usb = ["Bus 001 Device 003: ID 1AB1:04CE Rigol Technologies DS1054Z"]
        assert rigol.detect(usb, []) is True

    def test_detect_with_visa_resource(self, rigol):
        visa = ["USB0::1AB1::04CE::DS1ZA000000001::INSTR"]
        assert rigol.detect([], visa) is True

    def test_detect_no_match(self, rigol):
        usb = ["Bus 001 Device 003: ID ffff:0000 Unknown Device"]
        visa = ["GPIB0::1::INSTR"]
        assert rigol.detect(usb, visa) is False

    def test_detect_empty_lists(self, rigol):
        assert rigol.detect([], []) is False

    def test_detect_partial_vendor_match_in_usb(self, rigol):
        """Vendor ID substring in USB string is enough for detection."""
        usb = ["Bus 002 Device 007: ID 1ab1:9999 Rigol Other Device"]
        assert rigol.detect(usb, []) is True


# ---------------------------------------------------------------------------
# generate_example_code
# ---------------------------------------------------------------------------


class TestGenerateExampleCode:
    def test_non_empty(self, rigol):
        code = rigol.generate_example_code()
        assert len(code) > 0

    def test_contains_pyvisa_import(self, rigol):
        code = rigol.generate_example_code()
        assert "import pyvisa" in code

    def test_contains_key_scpi_commands(self, rigol):
        code = rigol.generate_example_code()
        assert ":CHANnel1:" in code or ":CHAN" in code
        assert ":MEASure:" in code or ":MEAS" in code

    def test_contains_idn_query(self, rigol):
        code = rigol.generate_example_code()
        assert "*IDN?" in code

    def test_contains_vendor_id(self, rigol):
        code = rigol.generate_example_code()
        assert "1AB1" in code

    def test_contains_scope_close(self, rigol):
        code = rigol.generate_example_code()
        assert ".close()" in code


# ---------------------------------------------------------------------------
# get_data_schema
# ---------------------------------------------------------------------------


class TestGetDataSchema:
    def test_returns_schema_instance(self, rigol):
        schema = rigol.get_data_schema()
        assert isinstance(schema, DeviceDataSchema)

    def test_has_firmware_version(self, rigol):
        schema = rigol.get_data_schema()
        assert "firmware_version" in schema.fields
        assert schema.fields["firmware_version"] == "str"

    def test_has_serial_number(self, rigol):
        schema = rigol.get_data_schema()
        assert "serial_number" in schema.fields
        assert schema.fields["serial_number"] == "str"

    def test_has_channels_available(self, rigol):
        schema = rigol.get_data_schema()
        assert "channels_available" in schema.fields
        assert schema.fields["channels_available"] == "int"
