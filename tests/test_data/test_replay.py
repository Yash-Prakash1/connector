"""Tests for hardware_agent.data.replay — ReplayEngine pattern execution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hardware_agent.core.models import ToolCall, ToolResult
from hardware_agent.data.replay import ReplayEngine
from hardware_agent.data.store import DataStore
from hardware_agent.devices.base import DeviceHints


# ── Helpers ───────────────────────────────────────────────────────────


def _high_confidence_pattern(
    fingerprint="abc123",
    steps=None,
    success_count=10,
    success_rate=0.95,
    confidence_score=9.0,
):
    """Build a pattern dict that passes the confidence threshold."""
    return {
        "id": "pat-hc",
        "device_type": "rigol_ds1054z",
        "os": "linux",
        "initial_state_fingerprint": fingerprint,
        "steps": steps
        or [
            {"action": "pip_install", "packages": ["pyvisa", "pyvisa-py"]},
            {"action": "verify", "pattern": "device_check"},
        ],
        "success_count": success_count,
        "success_rate": success_rate,
        "confidence_score": confidence_score,
    }


def _low_confidence_pattern(fingerprint="abc123"):
    """Build a pattern that does NOT pass the confidence threshold."""
    return {
        "id": "pat-lc",
        "device_type": "rigol_ds1054z",
        "os": "linux",
        "initial_state_fingerprint": fingerprint,
        "steps": [{"action": "pip_install", "packages": ["pyvisa"]}],
        "success_count": 2,
        "success_rate": 0.5,
        "confidence_score": 1.0,
    }


def _make_mock_executor(results=None):
    """Create a mock ToolExecutor.

    `results` is a list of ToolResult objects returned on successive calls.
    If None, every call returns success.
    """
    executor = MagicMock()
    if results is None:
        executor.execute.return_value = ToolResult(success=True, stdout="ok")
    else:
        executor.execute.side_effect = results
    return executor


def _make_mock_device_module(verify_result=(True, "Connected")):
    """Create a mock DeviceModule."""
    dm = MagicMock()
    dm.verify_connection.return_value = verify_result
    dm.get_info.return_value = MagicMock()
    dm.get_hints.return_value = DeviceHints(
        os_specific={
            "linux": {
                "udev_rule": 'SUBSYSTEM=="usb", ATTR{idVendor}=="1ab1", MODE="0666"',
                "udev_file": "/etc/udev/rules.d/99-rigol.rules",
                "udev_reload": "sudo udevadm control --reload-rules && sudo udevadm trigger",
            },
        },
    )
    return dm


# ── find_replay_candidate ────────────────────────────────────────────


class TestFindReplayCandidate:
    """Selecting a cached pattern for replay."""

    def test_returns_pattern_when_high_confidence(self, temp_db: DataStore):
        pattern = _high_confidence_pattern()
        temp_db.cache_patterns([pattern])

        engine = ReplayEngine()
        result = engine.find_replay_candidate(
            "rigol_ds1054z", "linux", "abc123", temp_db
        )

        assert result is not None
        assert result["id"] == "pat-hc"

    def test_returns_none_when_confidence_too_low(self, temp_db: DataStore):
        pattern = _low_confidence_pattern()
        temp_db.cache_patterns([pattern])

        engine = ReplayEngine()
        result = engine.find_replay_candidate(
            "rigol_ds1054z", "linux", "abc123", temp_db
        )

        assert result is None

    def test_returns_none_when_no_matching_patterns(self, temp_db: DataStore):
        # Cache patterns for a different device
        pattern = _high_confidence_pattern()
        pattern["device_type"] = "rigol_dp832"
        temp_db.cache_patterns([pattern])

        engine = ReplayEngine()
        result = engine.find_replay_candidate(
            "rigol_ds1054z", "linux", "abc123", temp_db
        )

        assert result is None

    def test_returns_none_when_fingerprint_mismatch(self, temp_db: DataStore):
        pattern = _high_confidence_pattern(fingerprint="different_fp")
        temp_db.cache_patterns([pattern])

        engine = ReplayEngine()
        result = engine.find_replay_candidate(
            "rigol_ds1054z", "linux", "abc123", temp_db
        )

        assert result is None

    def test_returns_pattern_with_null_fingerprint(self, temp_db: DataStore):
        """A pattern with no fingerprint matches any environment."""
        pattern = _high_confidence_pattern(fingerprint=None)
        # Override the fingerprint to None in the raw dict
        pattern["initial_state_fingerprint"] = None
        temp_db.cache_patterns([pattern])

        engine = ReplayEngine()
        result = engine.find_replay_candidate(
            "rigol_ds1054z", "linux", "any_fp", temp_db
        )

        assert result is not None

    def test_picks_first_qualifying_pattern(self, temp_db: DataStore):
        """Should return the first pattern that meets thresholds (ordered by confidence)."""
        p_best = _high_confidence_pattern(fingerprint="abc123")
        p_best["id"] = "best"
        p_best["confidence_score"] = 10.0

        p_good = _high_confidence_pattern(fingerprint="abc123")
        p_good["id"] = "good"
        p_good["confidence_score"] = 7.0

        temp_db.cache_patterns([p_good, p_best])  # caching order doesn't matter

        engine = ReplayEngine()
        result = engine.find_replay_candidate(
            "rigol_ds1054z", "linux", "abc123", temp_db
        )

        # Patterns are ordered by confidence_score DESC
        assert result["id"] == "best"


# ── execute_replay ────────────────────────────────────────────────────


class TestExecuteReplay:
    """Executing a replay pattern step-by-step."""

    def test_successful_replay(self):
        pattern = _high_confidence_pattern(
            steps=[
                {"action": "pip_install", "packages": ["pyvisa"]},
                {"action": "verify", "pattern": "device_check"},
            ]
        )
        executor = _make_mock_executor()
        device_module = _make_mock_device_module(verify_result=(True, "OK"))
        confirm = MagicMock(return_value=True)

        engine = ReplayEngine()
        result = engine.execute_replay(
            pattern, executor, device_module, "linux", confirm
        )

        assert result["success"] is True
        assert result["steps_executed"] == 2
        assert result["failed_at_step"] is None
        assert result["error"] is None
        assert executor.execute.call_count == 2
        device_module.verify_connection.assert_called_once()

    def test_failed_step_returns_failure(self):
        pattern = _high_confidence_pattern(
            steps=[
                {"action": "pip_install", "packages": ["pyvisa"]},
                {"action": "system_install", "target": "libusb"},
                {"action": "verify", "pattern": "device_check"},
            ]
        )
        executor = _make_mock_executor(
            results=[
                ToolResult(success=True, stdout="ok"),
                ToolResult(success=False, error="apt failed"),
                # Third step should not be reached
            ]
        )
        device_module = _make_mock_device_module()
        confirm = MagicMock(return_value=True)

        engine = ReplayEngine()
        result = engine.execute_replay(
            pattern, executor, device_module, "linux", confirm
        )

        assert result["success"] is False
        assert result["steps_executed"] == 2
        assert result["failed_at_step"] == 1
        assert result["error"] == "apt failed"
        # verify_connection should NOT have been called since we didn't finish
        device_module.verify_connection.assert_not_called()

    def test_user_declines_step(self):
        pattern = _high_confidence_pattern(
            steps=[
                {"action": "pip_install", "packages": ["pyvisa"]},
            ]
        )
        executor = _make_mock_executor()
        device_module = _make_mock_device_module()
        confirm = MagicMock(return_value=False)

        engine = ReplayEngine()
        result = engine.execute_replay(
            pattern, executor, device_module, "linux", confirm
        )

        assert result["success"] is False
        assert result["error"] == "User declined step"
        executor.execute.assert_not_called()

    def test_empty_steps_returns_failure(self):
        pattern = _high_confidence_pattern()
        # Explicitly set steps to empty after construction (bypassing the
        # `steps or default` in the helper).
        pattern["steps"] = []
        executor = _make_mock_executor()
        device_module = _make_mock_device_module()
        confirm = MagicMock(return_value=True)

        engine = ReplayEngine()
        result = engine.execute_replay(
            pattern, executor, device_module, "linux", confirm
        )

        assert result["success"] is False
        assert result["steps_executed"] == 0
        assert "No steps" in result["error"]

    def test_verify_connection_fails_after_all_steps(self):
        pattern = _high_confidence_pattern(
            steps=[{"action": "pip_install", "packages": ["pyvisa"]}]
        )
        executor = _make_mock_executor()
        device_module = _make_mock_device_module(
            verify_result=(False, "Device not responding")
        )
        confirm = MagicMock(return_value=True)

        engine = ReplayEngine()
        result = engine.execute_replay(
            pattern, executor, device_module, "linux", confirm
        )

        assert result["success"] is False
        assert result["steps_executed"] == 1
        assert result["error"] == "Device not responding"


# ── _expand_step ──────────────────────────────────────────────────────


class TestExpandStep:
    """Converting normalized steps back to executable ToolCalls."""

    def setup_method(self):
        self.engine = ReplayEngine()
        self.device_module = _make_mock_device_module()

    def test_expand_pip_install(self):
        step = {"action": "pip_install", "packages": ["pyvisa", "pyusb"]}
        tc = self.engine._expand_step(step, self.device_module, "linux")

        assert tc is not None
        assert tc.name == "pip_install"
        assert tc.parameters == {"packages": ["pyvisa", "pyusb"]}

    def test_expand_system_install_libusb_linux(self):
        step = {"action": "system_install", "target": "libusb"}
        tc = self.engine._expand_step(step, self.device_module, "linux")

        assert tc is not None
        assert tc.name == "bash"
        assert "apt install" in tc.parameters["command"]
        assert "libusb" in tc.parameters["command"]

    def test_expand_system_install_libusb_macos(self):
        step = {"action": "system_install", "target": "libusb"}
        tc = self.engine._expand_step(step, self.device_module, "macos")

        assert tc is not None
        assert tc.name == "bash"
        assert "brew install" in tc.parameters["command"]
        assert "libusb" in tc.parameters["command"]

    def test_expand_system_install_unknown_target(self):
        step = {"action": "system_install", "target": "unknown_pkg"}
        tc = self.engine._expand_step(step, self.device_module, "linux")
        assert tc is None

    def test_expand_permission_fix_udev_rule(self):
        step = {"action": "permission_fix", "pattern": "udev_rule"}
        tc = self.engine._expand_step(step, self.device_module, "linux")

        assert tc is not None
        assert tc.name == "bash"
        assert "tee" in tc.parameters["command"]
        assert "1ab1" in tc.parameters["command"]

    def test_expand_permission_fix_udev_reload(self):
        step = {"action": "permission_fix", "pattern": "udev_reload"}
        tc = self.engine._expand_step(step, self.device_module, "linux")

        assert tc is not None
        assert tc.name == "bash"
        assert "udevadm" in tc.parameters["command"]

    def test_expand_verify_device_check(self):
        step = {"action": "verify", "pattern": "device_check"}
        tc = self.engine._expand_step(step, self.device_module, "linux")

        assert tc is not None
        assert tc.name == "check_device"
        assert tc.parameters == {}

    def test_expand_verify_visa_list(self):
        step = {"action": "verify", "pattern": "visa_list"}
        tc = self.engine._expand_step(step, self.device_module, "linux")

        assert tc is not None
        assert tc.name == "list_visa_resources"

    def test_expand_verify_usb_list(self):
        step = {"action": "verify", "pattern": "usb_list"}
        tc = self.engine._expand_step(step, self.device_module, "linux")

        assert tc is not None
        assert tc.name == "list_usb_devices"

    def test_expand_verify_idn_query(self):
        step = {"action": "verify", "pattern": "idn_query"}
        tc = self.engine._expand_step(step, self.device_module, "linux")

        assert tc is not None
        assert tc.name == "check_device"

    def test_expand_unknown_action_returns_none(self):
        step = {"action": "unknown_action"}
        tc = self.engine._expand_step(step, self.device_module, "linux")
        assert tc is None
