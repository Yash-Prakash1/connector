"""Tests for hardware_agent.core.environment — EnvironmentDetector."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, mock_open, patch

import pytest

from hardware_agent.core.environment import (
    EnvironmentDetector,
    _detect_installed_packages,
    _detect_os,
    _detect_os_version,
    _detect_usb_devices,
    _detect_visa_resources,
    _detect_wsl,
)
from hardware_agent.core.models import OS, Environment


# ---------------------------------------------------------------------------
# _detect_os
# ---------------------------------------------------------------------------

class TestDetectOS:
    @patch("hardware_agent.core.environment.platform")
    def test_linux(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        assert _detect_os() == OS.LINUX

    @patch("hardware_agent.core.environment.platform")
    def test_macos(self, mock_platform):
        mock_platform.system.return_value = "Darwin"
        assert _detect_os() == OS.MACOS

    @patch("hardware_agent.core.environment.platform")
    def test_windows(self, mock_platform):
        mock_platform.system.return_value = "Windows"
        assert _detect_os() == OS.WINDOWS

    @patch("hardware_agent.core.environment.platform")
    def test_unknown_defaults_to_linux(self, mock_platform):
        mock_platform.system.return_value = "FreeBSD"
        assert _detect_os() == OS.LINUX


# ---------------------------------------------------------------------------
# _detect_os_version
# ---------------------------------------------------------------------------

class TestDetectOSVersion:
    @patch("hardware_agent.core.environment.subprocess.run")
    @patch("hardware_agent.core.environment.platform")
    def test_linux_lsb_release(self, mock_platform, mock_run):
        mock_platform.system.return_value = "Linux"
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Ubuntu 24.04 LTS\n"
        )
        result = _detect_os_version()
        assert result == "Ubuntu 24.04 LTS"
        mock_run.assert_called_once_with(
            ["lsb_release", "-ds"],
            capture_output=True, text=True, timeout=5,
        )

    @patch("hardware_agent.core.environment.subprocess.run")
    @patch("hardware_agent.core.environment.platform")
    def test_linux_lsb_release_failure_falls_back(self, mock_platform, mock_run):
        mock_platform.system.return_value = "Linux"
        mock_platform.platform.return_value = "Linux-6.5.0-generic-x86_64"
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = _detect_os_version()
        assert result == "Linux-6.5.0-generic-x86_64"

    @patch("hardware_agent.core.environment.subprocess.run")
    @patch("hardware_agent.core.environment.platform")
    def test_non_linux_uses_platform(self, mock_platform, mock_run):
        mock_platform.system.return_value = "Darwin"
        mock_platform.platform.return_value = "macOS-14.0-arm64"
        result = _detect_os_version()
        assert result == "macOS-14.0-arm64"
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# _detect_usb_devices
# ---------------------------------------------------------------------------

class TestDetectUSBDevices:
    @patch("hardware_agent.core.environment.subprocess.run")
    def test_linux_lsusb(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub\n"
                "Bus 001 Device 003: ID 1ab1:04ce Rigol Technologies DS1054Z\n"
            ),
        )
        devices = _detect_usb_devices(OS.LINUX)
        assert len(devices) == 2
        assert "Rigol Technologies DS1054Z" in devices[1]
        mock_run.assert_called_once_with(
            ["lsusb"], capture_output=True, text=True, timeout=5,
        )

    @patch("hardware_agent.core.environment.subprocess.run")
    def test_linux_lsusb_not_available(self, mock_run):
        mock_run.side_effect = FileNotFoundError("lsusb not found")
        devices = _detect_usb_devices(OS.LINUX)
        assert devices == []

    @patch("hardware_agent.core.environment.subprocess.run")
    def test_linux_lsusb_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        devices = _detect_usb_devices(OS.LINUX)
        assert devices == []

    @patch("hardware_agent.core.environment.subprocess.run")
    def test_macos_system_profiler(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="USB:\n  USB 3.0 Bus:\n    Host Controller\n",
        )
        devices = _detect_usb_devices(OS.MACOS)
        assert len(devices) == 3
        mock_run.assert_called_once_with(
            ["system_profiler", "SPUSBDataType"],
            capture_output=True, text=True, timeout=10,
        )

    @patch("hardware_agent.core.environment.subprocess.run")
    def test_windows_powershell(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="FriendlyName : USB Root Hub\n",
        )
        devices = _detect_usb_devices(OS.WINDOWS)
        assert len(devices) == 1
        mock_run.assert_called_once()

    @patch("hardware_agent.core.environment.subprocess.run")
    def test_empty_lines_filtered(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="line1\n\n\nline2\n",
        )
        devices = _detect_usb_devices(OS.LINUX)
        assert devices == ["line1", "line2"]


# ---------------------------------------------------------------------------
# _detect_installed_packages
# ---------------------------------------------------------------------------

class TestDetectInstalledPackages:
    @patch("hardware_agent.core.environment.subprocess.run")
    def test_parses_pip_json(self, mock_run):
        pip_output = json.dumps([
            {"name": "pyvisa", "version": "1.14.0"},
            {"name": "PyUSB", "version": "1.2.1"},
            {"name": "numpy", "version": "1.26.4"},
        ])
        mock_run.return_value = MagicMock(returncode=0, stdout=pip_output)
        packages = _detect_installed_packages("/usr/bin/pip3")
        assert packages == {
            "pyvisa": "1.14.0",
            "pyusb": "1.2.1",
            "numpy": "1.26.4",
        }
        mock_run.assert_called_once_with(
            ["/usr/bin/pip3", "list", "--format=json"],
            capture_output=True, text=True, timeout=15,
        )

    @patch("hardware_agent.core.environment.subprocess.run")
    def test_pip_failure_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        packages = _detect_installed_packages("/usr/bin/pip3")
        assert packages == {}

    @patch("hardware_agent.core.environment.subprocess.run")
    def test_pip_timeout_returns_empty(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pip", timeout=15)
        packages = _detect_installed_packages("/usr/bin/pip3")
        assert packages == {}

    @patch("hardware_agent.core.environment.subprocess.run")
    def test_pip_path_with_spaces_splits_correctly(self, mock_run):
        """When pip_path is 'python -m pip', it should be split."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([{"name": "pip", "version": "24.0"}]),
        )
        _detect_installed_packages("python -m pip")
        mock_run.assert_called_once_with(
            ["python", "-m", "pip", "list", "--format=json"],
            capture_output=True, text=True, timeout=15,
        )

    @patch("hardware_agent.core.environment.subprocess.run")
    def test_package_names_lowered(self, mock_run):
        pip_output = json.dumps([
            {"name": "PyVISA-py", "version": "0.7.0"},
        ])
        mock_run.return_value = MagicMock(returncode=0, stdout=pip_output)
        packages = _detect_installed_packages("/usr/bin/pip3")
        assert "pyvisa-py" in packages


# ---------------------------------------------------------------------------
# _detect_visa_resources
# ---------------------------------------------------------------------------

class TestDetectVisaResources:
    @patch("hardware_agent.core.environment.subprocess.run")
    def test_returns_visa_resources(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="USB0::0x1AB1::0x04CE::DS1ZA000000000::INSTR\n",
        )
        resources = _detect_visa_resources()
        assert len(resources) == 1
        assert "USB0::" in resources[0]

    @patch("hardware_agent.core.environment.subprocess.run")
    def test_pyvisa_not_installed(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        resources = _detect_visa_resources()
        assert resources == []

    @patch("hardware_agent.core.environment.subprocess.run")
    def test_exception_returns_empty(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        resources = _detect_visa_resources()
        assert resources == []


# ---------------------------------------------------------------------------
# _detect_wsl
# ---------------------------------------------------------------------------

class TestDetectWSL:
    @patch("hardware_agent.core.environment.platform")
    def test_wsl2_kernel_detected(self, mock_platform):
        mock_uname = MagicMock()
        mock_uname.release = "5.15.153.1-microsoft-standard-WSL2"
        mock_platform.uname.return_value = mock_uname
        assert _detect_wsl() is True

    @patch("hardware_agent.core.environment.platform")
    def test_wsl1_kernel_detected(self, mock_platform):
        mock_uname = MagicMock()
        mock_uname.release = "4.4.0-19041-Microsoft"
        mock_platform.uname.return_value = mock_uname
        assert _detect_wsl() is True

    @patch("hardware_agent.core.environment.platform")
    def test_native_linux_not_detected(self, mock_platform):
        mock_uname = MagicMock()
        mock_uname.release = "6.5.0-44-generic"
        mock_platform.uname.return_value = mock_uname
        with patch("builtins.open", side_effect=FileNotFoundError):
            assert _detect_wsl() is False

    @patch("hardware_agent.core.environment.platform")
    def test_proc_version_fallback(self, mock_platform):
        mock_uname = MagicMock()
        mock_uname.release = "unknown-kernel"
        mock_platform.uname.return_value = mock_uname
        proc_content = "Linux version 5.15.0 (Microsoft@Microsoft.com)"
        with patch("builtins.open", mock_open(read_data=proc_content)):
            assert _detect_wsl() is True

    @patch("hardware_agent.core.environment.platform")
    def test_proc_version_native_linux(self, mock_platform):
        mock_uname = MagicMock()
        mock_uname.release = "6.5.0-44-generic"
        mock_platform.uname.return_value = mock_uname
        proc_content = "Linux version 6.5.0-44-generic (buildd@lcy02-amd64)"
        with patch("builtins.open", mock_open(read_data=proc_content)):
            assert _detect_wsl() is False


# ---------------------------------------------------------------------------
# EnvironmentDetector.detect_current  (integration of all helpers)
# ---------------------------------------------------------------------------

class TestDetectCurrent:
    @patch("hardware_agent.core.environment._detect_visa_resources")
    @patch("hardware_agent.core.environment._detect_usb_devices")
    @patch("hardware_agent.core.environment._detect_installed_packages")
    @patch("hardware_agent.core.environment._detect_env")
    @patch("hardware_agent.core.environment._detect_pip_path")
    @patch("hardware_agent.core.environment._detect_os_version")
    @patch("hardware_agent.core.environment._detect_os")
    @patch("hardware_agent.core.environment.platform")
    @patch("hardware_agent.core.environment.sys")
    def test_detect_current_assembles_environment(
        self,
        mock_sys,
        mock_platform,
        mock_detect_os,
        mock_detect_os_version,
        mock_detect_pip_path,
        mock_detect_env,
        mock_detect_packages,
        mock_detect_usb,
        mock_detect_visa,
    ):
        mock_detect_os.return_value = OS.LINUX
        mock_detect_os_version.return_value = "Ubuntu 24.04"
        mock_platform.python_version.return_value = "3.12.0"
        mock_sys.executable = "/usr/bin/python3"
        mock_detect_pip_path.return_value = "/usr/bin/pip3"
        mock_detect_env.return_value = ("venv", "/home/user/venv", "venv")
        mock_detect_packages.return_value = {"pyvisa": "1.14.0"}
        mock_detect_usb.return_value = ["Bus 001 Device 003: Rigol"]
        mock_detect_visa.return_value = ["USB0::INSTR"]

        env = EnvironmentDetector.detect_current()

        assert isinstance(env, Environment)
        assert env.os == OS.LINUX
        assert env.os_version == "Ubuntu 24.04"
        assert env.pip_path == "/usr/bin/pip3"
        assert env.env_type == "venv"
        assert env.env_path == "/home/user/venv"
        assert env.installed_packages == {"pyvisa": "1.14.0"}
        assert len(env.usb_devices) == 1
        assert env.visa_resources == ["USB0::INSTR"]
