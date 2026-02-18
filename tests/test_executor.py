"""Tests for hardware_agent.core.executor — ToolExecutor."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from hardware_agent.core.executor import (
    BLOCKED_COMMANDS,
    REQUIRES_CONFIRMATION,
    ToolExecutor,
)
from hardware_agent.core.models import ToolCall, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_executor(mock_environment, device_module=None, confirm=None):
    """Create a ToolExecutor with sensible defaults for testing."""
    dm = device_module or MagicMock()
    return ToolExecutor(
        environment=mock_environment,
        device_module=dm,
        confirm_callback=confirm,
    )


def _call(executor, tool_name, params=None):
    """Shortcut: build a ToolCall and execute it."""
    tc = ToolCall(id=f"toolu_{tool_name}_test", name=tool_name, parameters=params or {})
    return executor.execute(tc)


# ---------------------------------------------------------------------------
# _handle_bash
# ---------------------------------------------------------------------------

class TestHandleBash:
    @patch("hardware_agent.core.executor.subprocess.run")
    def test_normal_command(self, mock_run, mock_environment):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="hello\n", stderr=""
        )
        executor = _make_executor(mock_environment)
        result = _call(executor, "bash", {"command": "echo hello"})

        assert result.success is True
        assert result.stdout == "hello\n"
        assert result.exit_code == 0
        mock_run.assert_called_once_with(
            "echo hello",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_blocked_command_rm_rf_root(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "bash", {"command": "rm -rf /"})
        assert result.success is False
        assert "Blocked" in result.error

    def test_blocked_command_fork_bomb(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "bash", {"command": ":(){:|:&};:"})
        assert result.success is False
        assert "Blocked" in result.error

    @pytest.mark.parametrize("blocked", BLOCKED_COMMANDS)
    def test_all_blocked_commands(self, blocked, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "bash", {"command": blocked})
        assert result.success is False

    def test_requires_confirmation_declined(self, mock_environment):
        executor = _make_executor(mock_environment, confirm=lambda _: False)
        result = _call(executor, "bash", {"command": "sudo apt update"})
        assert result.success is False
        assert "declined" in result.error.lower()

    @patch("hardware_agent.core.executor.subprocess.run")
    def test_requires_confirmation_accepted(self, mock_run, mock_environment):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        executor = _make_executor(mock_environment, confirm=lambda _: True)
        result = _call(executor, "bash", {"command": "sudo apt update"})
        assert result.success is True

    @patch("hardware_agent.core.executor.subprocess.run")
    def test_timeout(self, mock_run, mock_environment):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep 999", timeout=30)
        executor = _make_executor(mock_environment)
        result = _call(executor, "bash", {"command": "sleep 999"})
        assert result.success is False
        assert "timed out" in result.error.lower()

    @patch("hardware_agent.core.executor.subprocess.run")
    def test_nonzero_exit_code(self, mock_run, mock_environment):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="not found"
        )
        executor = _make_executor(mock_environment)
        result = _call(executor, "bash", {"command": "false"})
        assert result.success is False
        assert result.exit_code == 1
        assert result.stderr == "not found"

    @patch("hardware_agent.core.executor.subprocess.run")
    def test_custom_timeout_forwarded(self, mock_run, mock_environment):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        executor = _make_executor(mock_environment)
        _call(executor, "bash", {"command": "ls", "timeout": 60})
        mock_run.assert_called_once_with(
            "ls", shell=True, capture_output=True, text=True, timeout=60,
        )


# ---------------------------------------------------------------------------
# _handle_check_installed
# ---------------------------------------------------------------------------

class TestHandleCheckInstalled:
    def test_installed_package(self, mock_environment):
        """pip and setuptools are in mock_environment's installed_packages."""
        executor = _make_executor(mock_environment)
        result = _call(executor, "check_installed", {"package": "pip"})
        assert result.success is True
        assert "24.0" in result.stdout

    def test_missing_package(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "check_installed", {"package": "pyvisa"})
        assert result.success is False
        assert "NOT installed" in result.stdout

    def test_case_insensitive(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "check_installed", {"package": "PIP"})
        assert result.success is True


# ---------------------------------------------------------------------------
# _handle_pip_install
# ---------------------------------------------------------------------------

class TestHandlePipInstall:
    @patch("hardware_agent.core.executor.subprocess.run")
    def test_successful_install(self, mock_run, mock_environment):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Successfully installed pyvisa-1.14.0\n",
            stderr="",
        )
        executor = _make_executor(mock_environment, confirm=lambda _: True)
        result = _call(executor, "pip_install", {"packages": ["pyvisa"]})

        assert result.success is True
        assert "Successfully installed" in result.stdout
        # Package should be added to cache
        assert "pyvisa" in mock_environment.installed_packages

    @patch("hardware_agent.core.executor.subprocess.run")
    def test_install_multiple_packages(self, mock_run, mock_environment):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        executor = _make_executor(mock_environment, confirm=lambda _: True)
        result = _call(
            executor, "pip_install", {"packages": ["pyvisa", "pyusb"]}
        )
        assert result.success is True
        # Both packages should be in the cache
        assert "pyvisa" in mock_environment.installed_packages
        assert "pyusb" in mock_environment.installed_packages

    def test_declined_by_user(self, mock_environment):
        executor = _make_executor(mock_environment, confirm=lambda _: False)
        result = _call(executor, "pip_install", {"packages": ["pyvisa"]})
        assert result.success is False
        assert "declined" in result.error.lower()

    def test_no_packages_specified(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "pip_install", {"packages": []})
        assert result.success is False
        assert "No packages" in result.error

    @patch("hardware_agent.core.executor.subprocess.run")
    def test_pip_install_timeout(self, mock_run, mock_environment):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pip", timeout=120)
        executor = _make_executor(mock_environment, confirm=lambda _: True)
        result = _call(executor, "pip_install", {"packages": ["bigpackage"]})
        assert result.success is False
        assert "timed out" in result.error.lower()

    @patch("hardware_agent.core.executor.subprocess.run")
    def test_pip_install_failure(self, mock_run, mock_environment):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="No matching distribution"
        )
        executor = _make_executor(mock_environment, confirm=lambda _: True)
        result = _call(executor, "pip_install", {"packages": ["nonexistent"]})
        assert result.success is False
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# _handle_complete
# ---------------------------------------------------------------------------

class TestHandleComplete:
    def test_returns_terminal_success(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "complete", {
            "code": "import pyvisa; rm = pyvisa.ResourceManager()",
            "summary": "Installed pyvisa and connected",
        })
        assert result.success is True
        assert result.is_terminal is True
        assert "import pyvisa" in result.stdout
        assert "Summary:" in result.output

    def test_complete_without_summary(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "complete", {
            "code": "print('hello')",
        })
        assert result.success is True
        assert result.is_terminal is True
        assert result.stdout == "print('hello')"
        assert result.output == "print('hello')"


# ---------------------------------------------------------------------------
# _handle_give_up
# ---------------------------------------------------------------------------

class TestHandleGiveUp:
    def test_returns_terminal_failure(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "give_up", {
            "reason": "Device not found",
            "suggestions": ["Check USB cable", "Try different port"],
        })
        assert result.success is False
        assert result.is_terminal is True
        assert "Device not found" in result.error
        assert "Check USB cable" in result.output

    def test_give_up_without_suggestions(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "give_up", {"reason": "No connection"})
        assert result.success is False
        assert result.is_terminal is True
        assert "No connection" in result.error


# ---------------------------------------------------------------------------
# _handle_check_device
# ---------------------------------------------------------------------------

class TestHandleCheckDevice:
    def test_device_connected(self, mock_environment, mock_rigol_module):
        mock_rigol_module.verify_connection = MagicMock(
            return_value=(True, "RIGOL TECHNOLOGIES,DS1054Z,serial,version")
        )
        executor = _make_executor(mock_environment, device_module=mock_rigol_module)
        result = _call(executor, "check_device", {})
        assert result.success is True
        assert "RIGOL" in result.stdout
        mock_rigol_module.verify_connection.assert_called_once()

    def test_device_not_connected(self, mock_environment, mock_rigol_module):
        mock_rigol_module.verify_connection = MagicMock(
            return_value=(False, "No VISA resources found")
        )
        executor = _make_executor(mock_environment, device_module=mock_rigol_module)
        result = _call(executor, "check_device", {})
        assert result.success is False
        assert "No VISA resources" in result.error
        assert result.stdout == ""


# ---------------------------------------------------------------------------
# _handle_run_python
# ---------------------------------------------------------------------------

class TestHandleRunPython:
    @patch("hardware_agent.core.executor.subprocess.run")
    def test_successful_execution(self, mock_run, mock_environment):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="42\n", stderr=""
        )
        executor = _make_executor(mock_environment)
        result = _call(executor, "run_python", {"code": "print(42)"})
        assert result.success is True
        assert "42" in result.stdout

    @patch("hardware_agent.core.executor.subprocess.run")
    def test_execution_error(self, mock_run, mock_environment):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="NameError: name 'x' is not defined"
        )
        executor = _make_executor(mock_environment)
        result = _call(executor, "run_python", {"code": "print(x)"})
        assert result.success is False
        assert "NameError" in result.stderr

    @patch("hardware_agent.core.executor.subprocess.run")
    def test_timeout(self, mock_run, mock_environment):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="python", timeout=10)
        executor = _make_executor(mock_environment)
        result = _call(executor, "run_python", {
            "code": "import time; time.sleep(999)",
            "timeout": 10,
        })
        assert result.success is False
        assert "timed out" in result.error.lower()

    @patch("hardware_agent.core.executor.subprocess.run")
    def test_uses_environment_python_path(self, mock_run, mock_environment):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        executor = _make_executor(mock_environment)
        _call(executor, "run_python", {"code": "pass"})
        # The first argument to subprocess.run should use the env's python_path
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == mock_environment.python_path


# ---------------------------------------------------------------------------
# _handle_list_usb_devices
# ---------------------------------------------------------------------------

class TestHandleListUSBDevices:
    @patch("hardware_agent.core.executor.subprocess.run")
    def test_linux_calls_lsusb(self, mock_run, mock_environment):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Bus 001 Device 003: ID 1ab1:04ce Rigol\n",
            stderr="",
        )
        executor = _make_executor(mock_environment)
        result = _call(executor, "list_usb_devices", {})
        assert result.success is True
        assert "Rigol" in result.stdout
        mock_run.assert_called_once_with(
            "lsusb", shell=True, capture_output=True, text=True, timeout=5,
        )


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------

class TestUnknownTool:
    def test_unknown_tool_returns_error(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "nonexistent_tool", {})
        assert result.success is False
        assert "Unknown tool" in result.error
