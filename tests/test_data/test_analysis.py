"""Tests for hardware_agent.data.analysis — session analysis and normalization."""

from __future__ import annotations

import pytest

from hardware_agent.data.analysis import (
    _categorize_error,
    _error_fingerprint,
    analyze_session,
    normalize_iterations,
)

# make_iteration is in tests/conftest.py and imported automatically by pytest
from tests.conftest import make_iteration


# ── normalize_iterations ──────────────────────────────────────────────


class TestNormalizeIterations:
    """Convert raw iterations to normalized step patterns."""

    def test_pip_install_tool(self):
        iterations = [
            make_iteration(
                number=1,
                tool_name="pip_install",
                params={"packages": ["pyvisa", "pyusb"]},
                success=True,
            ),
        ]
        steps = normalize_iterations(iterations)
        assert len(steps) == 1
        assert steps[0]["action"] == "pip_install"
        assert steps[0]["packages"] == ["pyusb", "pyvisa"]  # sorted

    def test_bash_apt_install_libusb(self):
        iterations = [
            make_iteration(
                number=1,
                tool_name="bash",
                params={"command": "sudo apt install -y libusb-1.0-0-dev"},
                success=True,
            ),
        ]
        steps = normalize_iterations(iterations)
        assert len(steps) == 1
        assert steps[0]["action"] == "system_install"
        assert steps[0]["target"] == "libusb"

    def test_bash_apt_install_generic(self):
        iterations = [
            make_iteration(
                number=1,
                tool_name="bash",
                params={"command": "sudo apt install -y some-package"},
                success=True,
            ),
        ]
        steps = normalize_iterations(iterations)
        assert len(steps) == 1
        assert steps[0]["action"] == "system_install"
        assert steps[0]["target"] == "apt_package"

    def test_bash_udev_rule(self):
        iterations = [
            make_iteration(
                number=1,
                tool_name="bash",
                params={
                    "command": "echo 'SUBSYSTEM==\"usb\"...' | sudo tee /etc/udev/rules.d/99-rigol.rules"
                },
                success=True,
            ),
        ]
        steps = normalize_iterations(iterations)
        assert len(steps) == 1
        assert steps[0]["action"] == "permission_fix"
        assert steps[0]["pattern"] == "udev_rule"

    def test_bash_udevadm_reload(self):
        iterations = [
            make_iteration(
                number=1,
                tool_name="bash",
                params={
                    "command": "sudo udevadm control --reload-rules && sudo udevadm trigger"
                },
                success=True,
            ),
        ]
        steps = normalize_iterations(iterations)
        assert len(steps) == 1
        assert steps[0]["action"] == "permission_fix"
        assert steps[0]["pattern"] == "udev_reload"

    def test_check_device_normalized_to_verify(self):
        iterations = [
            make_iteration(
                number=1,
                tool_name="check_device",
                params={},
                success=True,
            ),
        ]
        steps = normalize_iterations(iterations)
        assert len(steps) == 1
        assert steps[0]["action"] == "verify"
        assert steps[0]["pattern"] == "device_check"

    def test_complete_is_skipped(self):
        iterations = [
            make_iteration(
                number=1,
                tool_name="complete",
                params={"summary": "All good"},
                success=True,
                is_terminal=True,
            ),
        ]
        steps = normalize_iterations(iterations)
        assert steps == []

    def test_give_up_is_skipped(self):
        iterations = [
            make_iteration(
                number=1,
                tool_name="give_up",
                params={"reason": "No device"},
                success=False,
                is_terminal=True,
            ),
        ]
        steps = normalize_iterations(iterations)
        assert steps == []

    def test_check_installed_is_skipped(self):
        iterations = [
            make_iteration(
                number=1,
                tool_name="check_installed",
                params={"package": "pyvisa"},
                success=True,
            ),
        ]
        steps = normalize_iterations(iterations)
        assert steps == []

    def test_list_visa_resources_normalized(self):
        iterations = [
            make_iteration(
                number=1,
                tool_name="list_visa_resources",
                params={},
                success=True,
            ),
        ]
        steps = normalize_iterations(iterations)
        assert len(steps) == 1
        assert steps[0]["action"] == "verify"
        assert steps[0]["pattern"] == "visa_list"

    def test_mixed_sequence(self):
        iterations = [
            make_iteration(1, "pip_install", {"packages": ["pyvisa"]}, True),
            make_iteration(
                2,
                "bash",
                {"command": "sudo apt install -y libusb-1.0-0-dev"},
                True,
            ),
            make_iteration(3, "check_device", {}, True),
            make_iteration(
                4,
                "complete",
                {"summary": "done"},
                True,
                is_terminal=True,
            ),
        ]
        steps = normalize_iterations(iterations)
        assert len(steps) == 3
        assert steps[0]["action"] == "pip_install"
        assert steps[1]["action"] == "system_install"
        assert steps[2]["action"] == "verify"

    def test_bash_pip_install(self):
        iterations = [
            make_iteration(
                number=1,
                tool_name="bash",
                params={"command": "pip install pyvisa pyvisa-py"},
                success=True,
            ),
        ]
        steps = normalize_iterations(iterations)
        assert len(steps) == 1
        assert steps[0]["action"] == "pip_install"
        assert "pyvisa" in steps[0]["packages"]
        assert "pyvisa-py" in steps[0]["packages"]


# ── analyze_session ───────────────────────────────────────────────────


class TestAnalyzeSession:
    """Full session analysis — error_resolutions extraction."""

    def test_error_resolution_pair(self):
        """A failed iteration followed by a success yields an ErrorResolution."""
        iterations = [
            make_iteration(
                number=1,
                tool_name="check_device",
                params={},
                success=False,
                stderr="No backend available",
            ),
            make_iteration(
                number=2,
                tool_name="pip_install",
                params={"packages": ["pyvisa-py"]},
                success=True,
                stdout="Installed pyvisa-py",
            ),
        ]
        analysis = analyze_session(iterations)

        assert len(analysis.error_resolutions) == 1
        er = analysis.error_resolutions[0]
        assert er.error_category == "backend"
        assert er.resolution_action == "pip_install"
        assert er.resolution_detail == {"packages": ["pyvisa-py"]}
        assert er.error_fingerprint  # non-empty hash

    def test_multiple_error_resolution_pairs(self):
        iterations = [
            make_iteration(
                1, "check_device", {}, False, stderr="Permission denied"
            ),
            make_iteration(
                2,
                "bash",
                {"command": "sudo chmod 666 /dev/usbtmc0"},
                True,
            ),
            make_iteration(
                3, "check_device", {}, False, stderr="timeout"
            ),
            make_iteration(4, "check_device", {}, True, stdout="Connected"),
        ]
        analysis = analyze_session(iterations)
        assert len(analysis.error_resolutions) == 2

    def test_no_resolutions_when_all_succeed(self):
        iterations = [
            make_iteration(1, "pip_install", {"packages": ["pyvisa"]}, True),
            make_iteration(2, "check_device", {}, True),
        ]
        analysis = analyze_session(iterations)
        assert analysis.error_resolutions == []

    def test_no_resolutions_when_all_fail(self):
        iterations = [
            make_iteration(1, "check_device", {}, False, stderr="error 1"),
            make_iteration(2, "check_device", {}, False, stderr="error 2"),
        ]
        analysis = analyze_session(iterations)
        assert analysis.error_resolutions == []

    def test_error_sequences_extracted(self):
        """Error followed by resolution followed by new error yields a sequence."""
        iterations = [
            make_iteration(
                1, "check_device", {}, False, stderr="No backend available"
            ),
            make_iteration(
                2, "pip_install", {"packages": ["pyvisa-py"]}, True
            ),
            make_iteration(
                3, "check_device", {}, False, stderr="Permission denied"
            ),
        ]
        analysis = analyze_session(iterations)
        assert len(analysis.error_sequences) == 1
        seq = analysis.error_sequences[0]
        assert seq.error_fingerprint  # from first error
        assert seq.next_error_fingerprint  # from second error
        assert seq.error_fingerprint != seq.next_error_fingerprint

    def test_pattern_populated_when_context_provided(self):
        """When device_type and os_name are given, pattern is set."""
        iterations = [
            make_iteration(1, "pip_install", {"packages": ["pyvisa"]}, True),
            make_iteration(2, "check_device", {}, True),
        ]
        analysis = analyze_session(
            iterations,
            device_type="rigol_ds1054z",
            os_name="linux",
            fingerprint="fp_abc",
            outcome="success",
        )
        assert analysis.pattern is not None
        assert analysis.pattern.device_type == "rigol_ds1054z"
        assert analysis.pattern.os == "linux"
        assert analysis.pattern.outcome == "success"
        assert analysis.pattern.initial_state_fingerprint == "fp_abc"
        assert len(analysis.pattern.steps) == 2
        assert analysis.pattern.steps[0].action == "pip_install"
        assert analysis.pattern.steps[1].action == "verify"

    def test_pattern_none_without_context(self):
        """Without device_type/os_name, pattern remains None."""
        iterations = [
            make_iteration(1, "pip_install", {"packages": ["pyvisa"]}, True),
        ]
        analysis = analyze_session(iterations)
        assert analysis.pattern is None

    def test_pattern_none_when_no_normalizable_steps(self):
        """Sessions with only terminal/diagnostic steps get no pattern."""
        iterations = [
            make_iteration(
                1, "complete", {"summary": "done"}, True, is_terminal=True
            ),
        ]
        analysis = analyze_session(
            iterations, device_type="rigol_ds1054z", os_name="linux"
        )
        assert analysis.pattern is None

    def test_error_resolutions_get_device_context(self):
        """Error resolutions inherit device_type/os when provided."""
        iterations = [
            make_iteration(
                1, "check_device", {}, False, stderr="No backend available"
            ),
            make_iteration(2, "pip_install", {"packages": ["pyvisa-py"]}, True),
        ]
        analysis = analyze_session(
            iterations, device_type="rigol_ds1054z", os_name="linux"
        )
        assert len(analysis.error_resolutions) == 1
        assert analysis.error_resolutions[0].device_type == "rigol_ds1054z"
        assert analysis.error_resolutions[0].os == "linux"


# ── _categorize_error ─────────────────────────────────────────────────


class TestCategorizeError:
    """Error categorization based on stderr/error text."""

    def test_permission_error(self):
        it = make_iteration(
            1, "bash", {}, False, stderr="Permission denied on /dev/usbtmc0"
        )
        assert _categorize_error(it) == "permissions"

    def test_errno_13(self):
        it = make_iteration(
            1, "bash", {}, False, stderr="[Errno 13] Permission denied"
        )
        assert _categorize_error(it) == "permissions"

    def test_not_found(self):
        it = make_iteration(
            1, "bash", {}, False, stderr="No such file or directory"
        )
        assert _categorize_error(it) == "not_found"

    def test_not_found_variant(self):
        it = make_iteration(
            1, "bash", {}, False, stderr="Device not found"
        )
        assert _categorize_error(it) == "not_found"

    def test_timeout(self):
        it = make_iteration(
            1, "check_device", {}, False, stderr="Connection timeout after 10s"
        )
        assert _categorize_error(it) == "timeout"

    def test_backend_no_backend(self):
        it = make_iteration(
            1, "check_device", {}, False, stderr="No backend available"
        )
        assert _categorize_error(it) == "backend"

    def test_backend_no_module(self):
        it = make_iteration(
            1, "run_python", {}, False, stderr="No module named 'usb'"
        )
        assert _categorize_error(it) == "backend"

    def test_driver_error(self):
        it = make_iteration(
            1, "bash", {}, False, stderr="driver not loaded"
        )
        assert _categorize_error(it) == "driver"

    def test_resource_busy(self):
        it = make_iteration(
            1, "check_device", {}, False, stderr="Device busy"
        )
        assert _categorize_error(it) == "resource_busy"

    def test_in_use(self):
        it = make_iteration(
            1, "check_device", {}, False, stderr="Resource in use"
        )
        assert _categorize_error(it) == "resource_busy"

    def test_unknown_error(self):
        it = make_iteration(
            1, "bash", {}, False, stderr="Something unexpected happened"
        )
        assert _categorize_error(it) == "unknown"

    def test_categorize_uses_error_field_when_no_stderr(self):
        it = make_iteration(
            1, "bash", {}, False, error="Permission denied"
        )
        assert _categorize_error(it) == "permissions"


# ── _error_fingerprint ────────────────────────────────────────────────


class TestErrorFingerprint:
    """Normalized error hashing."""

    def test_same_error_same_fingerprint(self):
        it1 = make_iteration(1, "bash", {}, False, stderr="No backend available")
        it2 = make_iteration(2, "bash", {}, False, stderr="No backend available")
        assert _error_fingerprint(it1) == _error_fingerprint(it2)

    def test_different_errors_different_fingerprint(self):
        it1 = make_iteration(1, "bash", {}, False, stderr="No backend available")
        it2 = make_iteration(2, "bash", {}, False, stderr="Permission denied")
        assert _error_fingerprint(it1) != _error_fingerprint(it2)

    def test_fingerprint_strips_paths(self):
        """Paths should be normalized so the same underlying error matches."""
        it1 = make_iteration(
            1, "bash", {}, False, stderr="Error: /home/user1/dev failed"
        )
        it2 = make_iteration(
            2, "bash", {}, False, stderr="Error: /home/user2/dev failed"
        )
        assert _error_fingerprint(it1) == _error_fingerprint(it2)

    def test_fingerprint_strips_versions(self):
        it1 = make_iteration(
            1, "bash", {}, False, stderr="pyvisa 1.12.0 error"
        )
        it2 = make_iteration(
            2, "bash", {}, False, stderr="pyvisa 1.13.1 error"
        )
        assert _error_fingerprint(it1) == _error_fingerprint(it2)

    def test_fingerprint_is_12_char_hex(self):
        it = make_iteration(1, "bash", {}, False, stderr="some error")
        fp = _error_fingerprint(it)
        assert len(fp) == 12
        assert all(c in "0123456789abcdef" for c in fp)
