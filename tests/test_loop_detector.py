"""Tests for hardware_agent.core.loop_detector — LoopDetector."""

from __future__ import annotations

import pytest

from hardware_agent.core.loop_detector import LoopDetector, LoopWarning
from hardware_agent.core.models import ToolCall, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_call(name="bash", params=None):
    return ToolCall(
        id=f"toolu_{name}_001",
        name=name,
        parameters=params or {"command": "lsusb"},
    )


def _make_result(success=True, stderr="", error="", stdout=""):
    return ToolResult(
        success=success, stdout=stdout, stderr=stderr, error=error,
    )


# ---------------------------------------------------------------------------
# First failure: no loop detected
# ---------------------------------------------------------------------------

class TestFirstFailure:
    def test_single_failure_not_a_loop(self):
        detector = LoopDetector(max_repeats=2)
        tc = _make_tool_call()
        result = _make_result(success=False, stderr="command not found")
        warning = detector.check(tc, result)
        assert warning.is_loop is False
        assert warning.message == ""

    def test_single_failure_with_error_field(self):
        detector = LoopDetector(max_repeats=3)
        tc = _make_tool_call("pip_install", {"packages": ["pyvisa"]})
        result = _make_result(success=False, error="No matching distribution")
        warning = detector.check(tc, result)
        assert warning.is_loop is False


# ---------------------------------------------------------------------------
# Same action + error repeated -> loop detected after max_repeats
# ---------------------------------------------------------------------------

class TestRepeatedFailure:
    def test_loop_detected_at_max_repeats(self):
        detector = LoopDetector(max_repeats=2)
        tc = _make_tool_call("bash", {"command": "lsusb"})
        bad_result = _make_result(success=False, stderr="permission denied")

        # First failure — no loop
        w1 = detector.check(tc, bad_result)
        assert w1.is_loop is False

        # Second failure (same action+error) — loop triggered
        w2 = detector.check(tc, bad_result)
        assert w2.is_loop is True
        assert "same error" in w2.message.lower()
        assert "2 times" in w2.message

    def test_loop_detected_at_max_repeats_3(self):
        detector = LoopDetector(max_repeats=3)
        tc = _make_tool_call("run_python", {"code": "import pyvisa"})
        bad_result = _make_result(success=False, stderr="ModuleNotFoundError")

        for _ in range(2):
            w = detector.check(tc, bad_result)
            assert w.is_loop is False

        w3 = detector.check(tc, bad_result)
        assert w3.is_loop is True

    def test_loop_message_mentions_tool_name(self):
        detector = LoopDetector(max_repeats=2)
        tc = _make_tool_call("check_device")
        bad_result = _make_result(success=False, error="No VISA resources")
        detector.check(tc, bad_result)
        w = detector.check(tc, bad_result)
        assert "check_device" in w.message

    def test_continues_counting_beyond_threshold(self):
        """Even after loop detected, subsequent identical failures keep counting."""
        detector = LoopDetector(max_repeats=2)
        tc = _make_tool_call()
        bad_result = _make_result(success=False, stderr="err")
        detector.check(tc, bad_result)
        detector.check(tc, bad_result)  # loop detected
        w = detector.check(tc, bad_result)  # 3rd time
        assert w.is_loop is True
        assert "3 times" in w.message


# ---------------------------------------------------------------------------
# Success resets: successful result doesn't trigger loop
# ---------------------------------------------------------------------------

class TestSuccessDoesNotTrigger:
    def test_success_returns_no_loop(self):
        detector = LoopDetector(max_repeats=2)
        tc = _make_tool_call()
        ok_result = _make_result(success=True, stdout="ok")
        w = detector.check(tc, ok_result)
        assert w.is_loop is False

    def test_failure_then_success_then_failure_no_loop(self):
        """
        A success between identical failures should NOT prevent loop detection
        because the LoopDetector counts by (action, error) pair, and success
        doesn't decrement. However, it does return no-loop for the success call.
        After the success, the second failure is still count=2 so loop triggers.
        """
        detector = LoopDetector(max_repeats=2)
        tc = _make_tool_call("bash", {"command": "lsusb"})
        bad_result = _make_result(success=False, stderr="denied")
        ok_result = _make_result(success=True, stdout="Bus 001")

        w1 = detector.check(tc, bad_result)  # count=1
        assert w1.is_loop is False

        w_ok = detector.check(tc, ok_result)  # success — skipped
        assert w_ok.is_loop is False

        w2 = detector.check(tc, bad_result)  # count=2 -> loop
        assert w2.is_loop is True

    def test_many_successes_no_loop(self):
        detector = LoopDetector(max_repeats=2)
        tc = _make_tool_call()
        ok_result = _make_result(success=True, stdout="fine")
        for _ in range(10):
            w = detector.check(tc, ok_result)
            assert w.is_loop is False


# ---------------------------------------------------------------------------
# Different errors don't trigger loop
# ---------------------------------------------------------------------------

class TestDifferentErrors:
    def test_same_action_different_errors(self):
        detector = LoopDetector(max_repeats=2)
        tc = _make_tool_call("bash", {"command": "pip install pyvisa"})
        err1 = _make_result(success=False, stderr="permission denied")
        err2 = _make_result(success=False, stderr="network unreachable")

        w1 = detector.check(tc, err1)
        assert w1.is_loop is False

        # Different error text -> different pair key -> count starts at 1
        w2 = detector.check(tc, err2)
        assert w2.is_loop is False

    def test_different_actions_same_error(self):
        detector = LoopDetector(max_repeats=2)
        err = _make_result(success=False, stderr="timeout")

        tc1 = _make_tool_call("bash", {"command": "lsusb"})
        tc2 = _make_tool_call("bash", {"command": "lsusb -v"})

        w1 = detector.check(tc1, err)
        assert w1.is_loop is False
        w2 = detector.check(tc2, err)
        assert w2.is_loop is False

    def test_completely_different_tools(self):
        detector = LoopDetector(max_repeats=2)
        err = _make_result(success=False, error="failed")

        tc_bash = _make_tool_call("bash", {"command": "ls"})
        tc_python = _make_tool_call("run_python", {"code": "pass"})

        detector.check(tc_bash, err)
        w = detector.check(tc_python, err)
        assert w.is_loop is False


# ---------------------------------------------------------------------------
# get_loop_breaker_message
# ---------------------------------------------------------------------------

class TestGetLoopBreakerMessage:
    def test_returns_non_empty_string(self):
        detector = LoopDetector()
        msg = detector.get_loop_breaker_message()
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_message_content(self):
        detector = LoopDetector()
        msg = detector.get_loop_breaker_message()
        assert "different approach" in msg.lower()
        assert "give_up" in msg


# ---------------------------------------------------------------------------
# History pruning
# ---------------------------------------------------------------------------

class TestHistoryPruning:
    def test_history_pruned_to_history_size(self):
        detector = LoopDetector(max_repeats=100, history_size=5)
        for i in range(20):
            tc = _make_tool_call("bash", {"command": f"cmd_{i}"})
            err = _make_result(success=False, stderr=f"err_{i}")
            detector.check(tc, err)
        assert len(detector._history) == 5
