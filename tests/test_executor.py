"""Tests for hardware_agent.core.executor — ToolExecutor."""

from __future__ import annotations

import subprocess
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from hardware_agent.core.executor import (
    AskUserCallback,
    BLOCKED_COMMANDS,
    REQUIRES_CONFIRMATION,
    ToolExecutor,
    _html_to_text,
)
from hardware_agent.core.models import ToolCall, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_executor(mock_environment, device_module=None, confirm=None, ask_user=None):
    """Create a ToolExecutor with sensible defaults for testing."""
    dm = device_module or MagicMock()
    return ToolExecutor(
        environment=mock_environment,
        device_module=dm,
        confirm_callback=confirm,
        ask_user_callback=ask_user,
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
            "summary": "Installed pyvisa and connected to Rigol DS1054Z",
        })
        assert result.success is True
        assert result.is_terminal is True
        assert "Installed pyvisa" in result.stdout
        assert "Installed pyvisa" in result.output

    def test_complete_without_summary(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "complete", {})
        assert result.success is True
        assert result.is_terminal is True
        assert result.stdout == "Session completed."
        assert result.output == "Session completed."


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

# ---------------------------------------------------------------------------
# _handle_ask_user
# ---------------------------------------------------------------------------

class TestHandleAskUser:
    def test_free_form_question(self, mock_environment):
        callback = MagicMock(return_value="USB cable")
        executor = _make_executor(mock_environment, ask_user=callback)
        result = _call(executor, "ask_user", {"question": "How is the device connected?"})
        assert result.success is True
        assert result.stdout == "USB cable"
        callback.assert_called_once_with("How is the device connected?", None)

    def test_multiple_choice(self, mock_environment):
        callback = MagicMock(return_value="USB")
        executor = _make_executor(mock_environment, ask_user=callback)
        result = _call(executor, "ask_user", {
            "question": "Connection type?",
            "choices": ["USB", "Ethernet", "GPIB"],
        })
        assert result.success is True
        assert result.stdout == "USB"
        callback.assert_called_once_with(
            "Connection type?", ["USB", "Ethernet", "GPIB"]
        )

    def test_no_callback_returns_error(self, mock_environment):
        executor = _make_executor(mock_environment, ask_user=None)
        result = _call(executor, "ask_user", {"question": "Are you there?"})
        assert result.success is False
        assert "non-interactive" in result.error.lower()

    def test_empty_question_returns_error(self, mock_environment):
        callback = MagicMock(return_value="yes")
        executor = _make_executor(mock_environment, ask_user=callback)
        result = _call(executor, "ask_user", {"question": ""})
        assert result.success is False
        assert "No question" in result.error
        callback.assert_not_called()

    def test_keyboard_interrupt_handled(self, mock_environment):
        callback = MagicMock(side_effect=KeyboardInterrupt)
        executor = _make_executor(mock_environment, ask_user=callback)
        result = _call(executor, "ask_user", {"question": "Still there?"})
        assert result.success is False
        assert "cancelled" in result.error.lower()

    def test_eof_error_handled(self, mock_environment):
        callback = MagicMock(side_effect=EOFError)
        executor = _make_executor(mock_environment, ask_user=callback)
        result = _call(executor, "ask_user", {"question": "Still there?"})
        assert result.success is False
        assert "cancelled" in result.error.lower()


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------

class TestUnknownTool:
    def test_unknown_tool_returns_error(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "nonexistent_tool", {})
        assert result.success is False
        assert "Unknown tool" in result.error


# ---------------------------------------------------------------------------
# _handle_web_search
# ---------------------------------------------------------------------------

class TestHandleWebSearch:
    @patch("hardware_agent.core.executor.DDGS", create=True)
    def test_success(self, MockDDGS, mock_environment):
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.__enter__ = MagicMock(return_value=mock_ddgs_instance)
        mock_ddgs_instance.__exit__ = MagicMock(return_value=False)
        mock_ddgs_instance.text.return_value = [
            {"title": "Fix VISA", "href": "https://example.com", "body": "Install pyvisa-py"},
        ]
        # Patch the lazy import inside the handler
        with patch.dict("sys.modules", {"duckduckgo_search": MagicMock(DDGS=lambda: mock_ddgs_instance)}):
            executor = _make_executor(mock_environment)
            result = _call(executor, "web_search", {"query": "pyvisa no backend"})
        assert result.success is True
        assert "Fix VISA" in result.stdout
        assert "example.com" in result.stdout

    def test_empty_query(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "web_search", {"query": ""})
        assert result.success is False
        assert "No search query" in result.error

    def test_import_error(self, mock_environment):
        with patch.dict("sys.modules", {"duckduckgo_search": None}):
            executor = _make_executor(mock_environment)
            result = _call(executor, "web_search", {"query": "test"})
        assert result.success is False
        assert "not installed" in result.error

    def test_search_failure(self, mock_environment):
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.__enter__ = MagicMock(return_value=mock_ddgs_instance)
        mock_ddgs_instance.__exit__ = MagicMock(return_value=False)
        mock_ddgs_instance.text.side_effect = RuntimeError("rate limited")
        with patch.dict("sys.modules", {"duckduckgo_search": MagicMock(DDGS=lambda: mock_ddgs_instance)}):
            executor = _make_executor(mock_environment)
            result = _call(executor, "web_search", {"query": "test"})
        assert result.success is False
        assert "Search failed" in result.error


# ---------------------------------------------------------------------------
# _handle_web_fetch
# ---------------------------------------------------------------------------

class TestHandleWebFetch:
    @patch("hardware_agent.core.executor.urllib.request.urlopen")
    def test_success(self, mock_urlopen, mock_environment):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html><body><p>Hello world</p></body></html>"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        executor = _make_executor(mock_environment)
        result = _call(executor, "web_fetch", {"url": "https://example.com"})
        assert result.success is True
        assert "Hello world" in result.stdout

    def test_empty_url(self, mock_environment):
        executor = _make_executor(mock_environment)
        result = _call(executor, "web_fetch", {"url": ""})
        assert result.success is False
        assert "No URL" in result.error

    @patch("hardware_agent.core.executor.urllib.request.urlopen")
    def test_timeout(self, mock_urlopen, mock_environment):
        mock_urlopen.side_effect = urllib.request.URLError("timed out")
        executor = _make_executor(mock_environment)
        result = _call(executor, "web_fetch", {"url": "https://example.com"})
        assert result.success is False
        assert "Fetch failed" in result.error

    @patch("hardware_agent.core.executor.urllib.request.urlopen")
    def test_content_truncation(self, mock_urlopen, mock_environment):
        long_text = "x" * 10000
        mock_resp = MagicMock()
        mock_resp.read.return_value = f"<html><body>{long_text}</body></html>".encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        executor = _make_executor(mock_environment)
        result = _call(executor, "web_fetch", {"url": "https://example.com"})
        assert result.success is True
        assert "truncated" in result.stdout
        # Content should be capped at 8000 + truncation message
        assert len(result.stdout) < 8100


# ---------------------------------------------------------------------------
# _handle_run_user_script
# ---------------------------------------------------------------------------

class TestHandleRunUserScript:
    @patch("hardware_agent.core.executor.subprocess.run")
    def test_success_with_confirmation(self, mock_run, mock_environment, tmp_path):
        script = tmp_path / "test_script.py"
        script.write_text("print('hello')")
        mock_run.return_value = MagicMock(
            returncode=0, stdout="hello\n", stderr=""
        )
        executor = _make_executor(mock_environment, confirm=lambda _: True)
        result = _call(executor, "run_user_script", {"path": str(script)})
        assert result.success is True
        assert "hello" in result.stdout

    def test_declined_by_user(self, mock_environment, tmp_path):
        script = tmp_path / "test_script.py"
        script.write_text("print('hello')")
        executor = _make_executor(mock_environment, confirm=lambda _: False)
        result = _call(executor, "run_user_script", {"path": str(script)})
        assert result.success is False
        assert "declined" in result.error.lower()

    def test_file_not_found(self, mock_environment):
        executor = _make_executor(mock_environment, confirm=lambda _: True)
        result = _call(executor, "run_user_script", {"path": "/nonexistent/script.py"})
        assert result.success is False
        assert "not found" in result.error.lower()

    @patch("hardware_agent.core.executor.subprocess.run")
    def test_timeout_cap_enforced(self, mock_run, mock_environment, tmp_path):
        script = tmp_path / "test_script.py"
        script.write_text("import time; time.sleep(999)")
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="python", timeout=120)
        executor = _make_executor(mock_environment, confirm=lambda _: True)
        # Request 200s timeout, should be capped to 120
        result = _call(executor, "run_user_script", {"path": str(script), "timeout": 200})
        assert result.success is False
        assert "timed out" in result.error.lower()
        # Verify subprocess was called with capped timeout
        call_kwargs = mock_run.call_args
        assert call_kwargs[1]["timeout"] == 120


# ---------------------------------------------------------------------------
# _html_to_text helper
# ---------------------------------------------------------------------------

class TestHtmlToText:
    def test_basic_extraction(self):
        html = "<html><body><p>Hello</p><p>World</p></body></html>"
        assert "Hello" in _html_to_text(html)
        assert "World" in _html_to_text(html)

    def test_skips_script_tags(self):
        html = "<html><body><script>var x=1;</script><p>Visible</p></body></html>"
        text = _html_to_text(html)
        assert "var x" not in text
        assert "Visible" in text

    def test_skips_style_tags(self):
        html = "<html><body><style>.foo{color:red}</style><p>Visible</p></body></html>"
        text = _html_to_text(html)
        assert "color" not in text
        assert "Visible" in text

    def test_skips_nav_tags(self):
        html = "<html><body><nav>Menu items</nav><p>Content</p></body></html>"
        text = _html_to_text(html)
        assert "Menu" not in text
        assert "Content" in text
