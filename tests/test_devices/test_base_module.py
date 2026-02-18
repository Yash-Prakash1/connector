"""Tests for hardware_agent.devices.base — ABC, dataclasses, and _run_python helper."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from hardware_agent.devices.base import (
    DeviceDataSchema,
    DeviceHints,
    DeviceInfo,
    DeviceModule,
)


# ---------------------------------------------------------------------------
# DeviceModule ABC cannot be instantiated
# ---------------------------------------------------------------------------


class TestDeviceModuleABC:
    """DeviceModule is abstract and must not be instantiated directly."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            DeviceModule()

    def test_subclass_missing_methods_cannot_instantiate(self):
        """A subclass that does not implement every abstract method is still abstract."""

        class PartialDevice(DeviceModule):
            def get_info(self):
                return None

        with pytest.raises(TypeError):
            PartialDevice()

    def test_concrete_subclass_can_instantiate(self):
        """A subclass implementing all abstract methods can be created."""

        class ConcreteDevice(DeviceModule):
            def get_info(self):
                return DeviceInfo(
                    identifier="test",
                    name="Test",
                    manufacturer="Acme",
                    category="test",
                    model_patterns=[],
                    connection_type="usb",
                )

            def get_hints(self, os):
                return DeviceHints()

            def detect(self, usb_devices, visa_resources):
                return False

            def verify_connection(self):
                return (True, "ok")

            def generate_example_code(self):
                return ""

            def get_data_schema(self):
                return DeviceDataSchema()

        device = ConcreteDevice()
        assert device.get_info().identifier == "test"


# ---------------------------------------------------------------------------
# Dataclass construction
# ---------------------------------------------------------------------------


class TestDeviceInfo:
    def test_creation(self):
        info = DeviceInfo(
            identifier="my_device",
            name="My Device",
            manufacturer="TestCorp",
            category="sensor",
            model_patterns=["MD-100", "MD-200"],
            connection_type="serial",
        )
        assert info.identifier == "my_device"
        assert info.name == "My Device"
        assert info.manufacturer == "TestCorp"
        assert info.category == "sensor"
        assert info.model_patterns == ["MD-100", "MD-200"]
        assert info.connection_type == "serial"

    def test_model_patterns_is_list(self):
        info = DeviceInfo(
            identifier="x",
            name="x",
            manufacturer="x",
            category="x",
            model_patterns=[],
            connection_type="x",
        )
        assert isinstance(info.model_patterns, list)


class TestDeviceHints:
    def test_defaults(self):
        hints = DeviceHints()
        assert hints.common_errors == {}
        assert hints.setup_steps == []
        assert hints.os_specific == {}
        assert hints.documentation_urls == []
        assert hints.known_quirks == []
        assert hints.required_packages == []

    def test_custom_values(self):
        hints = DeviceHints(
            common_errors={"err": "fix"},
            setup_steps=["step 1"],
            os_specific={"linux": {"key": "val"}},
            documentation_urls=["https://example.com"],
            known_quirks=["quirk"],
            required_packages=["pkg"],
        )
        assert hints.common_errors == {"err": "fix"}
        assert hints.setup_steps == ["step 1"]
        assert hints.os_specific == {"linux": {"key": "val"}}
        assert hints.documentation_urls == ["https://example.com"]
        assert hints.known_quirks == ["quirk"]
        assert hints.required_packages == ["pkg"]


class TestDeviceDataSchema:
    def test_defaults(self):
        schema = DeviceDataSchema()
        assert schema.fields == {}

    def test_custom_fields(self):
        schema = DeviceDataSchema(fields={"voltage": "float", "label": "str"})
        assert schema.fields["voltage"] == "float"
        assert schema.fields["label"] == "str"


# ---------------------------------------------------------------------------
# _run_python helper
# ---------------------------------------------------------------------------


class _MinimalDevice(DeviceModule):
    """Minimal concrete subclass so we can call _run_python."""

    def get_info(self):
        return DeviceInfo("t", "t", "t", "t", [], "t")

    def get_hints(self, os):
        return DeviceHints()

    def detect(self, usb_devices, visa_resources):
        return False

    def verify_connection(self):
        return (True, "ok")

    def generate_example_code(self):
        return ""

    def get_data_schema(self):
        return DeviceDataSchema()


class TestRunPython:
    """Tests for DeviceModule._run_python with subprocess.run mocked."""

    def setup_method(self):
        self.device = _MinimalDevice()

    @patch("hardware_agent.devices.base.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="hello world", stderr=""
        )
        success, output = self.device._run_python("print('hello world')")
        assert success is True
        assert output == "hello world"
        mock_run.assert_called_once()

    @patch("hardware_agent.devices.base.subprocess.run")
    def test_failure_nonzero_returncode(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Traceback..."
        )
        success, output = self.device._run_python("import bad")
        assert success is False
        assert "Traceback" in output

    @patch("hardware_agent.devices.base.subprocess.run")
    def test_stdout_and_stderr_combined(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="out", stderr="warn"
        )
        success, output = self.device._run_python("code")
        assert success is True
        assert "out" in output
        assert "warn" in output

    @patch("hardware_agent.devices.base.subprocess.run")
    def test_timeout_expired(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="python", timeout=10)
        success, output = self.device._run_python("while True: pass", timeout=10)
        assert success is False
        assert "Timeout" in output
        assert "10" in output

    @patch("hardware_agent.devices.base.subprocess.run")
    def test_generic_exception(self, mock_run):
        mock_run.side_effect = OSError("disk failure")
        success, output = self.device._run_python("code")
        assert success is False
        assert "disk failure" in output

    @patch("hardware_agent.devices.base.subprocess.run")
    def test_empty_stdout_with_stderr_no_leading_newline(self, mock_run):
        """When stdout is empty and stderr has content, no leading newline."""
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error msg"
        )
        success, output = self.device._run_python("code")
        assert success is False
        assert output == "error msg"
        assert not output.startswith("\n")
