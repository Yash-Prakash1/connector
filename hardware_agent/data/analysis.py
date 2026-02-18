"""Post-session analysis — extracts shareable patterns from iteration logs."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

from hardware_agent.core.models import Iteration
from hardware_agent.data.models import (
    ErrorResolution,
    ErrorSequence,
    NormalizedStep,
    ResolutionPattern,
    SessionAnalysis,
)


def analyze_session(iterations: list[Iteration]) -> SessionAnalysis:
    """Analyze a completed session and extract shareable patterns."""
    error_resolutions = _extract_error_resolutions(iterations)
    error_sequences = _extract_error_sequences(iterations)
    normalized_steps = normalize_iterations(iterations)

    return SessionAnalysis(
        error_resolutions=error_resolutions,
        error_sequences=error_sequences,
    )


def normalize_iterations(iterations: list[Iteration]) -> list[dict]:
    """Convert raw iterations to normalized step patterns for sharing."""
    steps = []
    for it in iterations:
        step = _normalize_tool_call(it.tool_call.name, it.tool_call.parameters)
        if step is not None:
            steps.append(step)
    return steps


def _normalize_tool_call(
    tool_name: str, params: dict[str, Any]
) -> Optional[dict]:
    """Normalize a raw tool call to an abstract pattern."""
    if tool_name == "pip_install":
        packages = params.get("packages", [])
        if packages:
            return {"action": "pip_install", "packages": sorted(packages)}

    elif tool_name == "bash":
        command = params.get("command", "")
        return _normalize_bash_command(command)

    elif tool_name == "run_python":
        code = params.get("code", "")
        return _normalize_python_code(code)

    elif tool_name == "check_device":
        return {"action": "verify", "pattern": "device_check"}

    elif tool_name == "list_visa_resources":
        return {"action": "verify", "pattern": "visa_list"}

    elif tool_name == "list_usb_devices":
        return {"action": "verify", "pattern": "usb_list"}

    elif tool_name == "check_installed":
        return None  # Diagnostic, not a state-changing step

    elif tool_name in ("complete", "give_up"):
        return None  # Terminal, not a step

    return None


def _normalize_bash_command(command: str) -> Optional[dict]:
    """Normalize a bash command to an abstract pattern."""
    # pip install
    if re.match(r"^\s*pip\s+install\s+", command):
        packages = re.findall(r"pip\s+install\s+(.*)", command)
        if packages:
            pkgs = [
                p.strip()
                for p in packages[0].split()
                if not p.startswith("-")
            ]
            return {"action": "pip_install", "packages": sorted(pkgs)}

    # apt install
    if re.search(r"apt\s+(install|get\s+install)", command):
        if "libusb" in command:
            return {"action": "system_install", "target": "libusb"}
        return {"action": "system_install", "target": "apt_package"}

    # brew install
    if re.search(r"brew\s+install", command):
        if "libusb" in command:
            return {"action": "system_install", "target": "libusb"}
        return {"action": "system_install", "target": "brew_package"}

    # udev rules
    if "udev" in command or "/etc/udev" in command:
        if "udevadm" in command:
            return {"action": "permission_fix", "pattern": "udev_reload"}
        return {"action": "permission_fix", "pattern": "udev_rule"}

    # usermod / group permissions
    if "usermod" in command or "dialout" in command:
        return {"action": "permission_fix", "pattern": "dialout_group"}

    # lsusb
    if command.strip().startswith("lsusb"):
        return {"action": "verify", "pattern": "usb_list"}

    return None


def _normalize_python_code(code: str) -> Optional[dict]:
    """Normalize Python code execution to an abstract pattern."""
    if "*IDN?" in code or "idn" in code.lower():
        return {"action": "verify", "pattern": "idn_query"}
    if "list_resources" in code:
        return {"action": "verify", "pattern": "visa_list"}
    if "import pyvisa" in code:
        return {"action": "verify", "pattern": "visa_check"}
    return None


def _extract_error_resolutions(
    iterations: list[Iteration],
) -> list[ErrorResolution]:
    """Find error→resolution pairs in iteration history."""
    resolutions: list[ErrorResolution] = []
    failed_iterations: list[Iteration] = []

    for it in iterations:
        if not it.result.success:
            failed_iterations.append(it)
        elif failed_iterations:
            # This success might resolve a prior failure
            last_failure = failed_iterations[-1]
            error_fp = _error_fingerprint(last_failure)
            error_cat = _categorize_error(last_failure)
            resolution_action = it.tool_call.name
            resolution_detail = it.tool_call.parameters

            if error_fp:
                resolutions.append(ErrorResolution(
                    device_type=None,
                    os=None,
                    error_fingerprint=error_fp,
                    error_category=error_cat,
                    explanation=_error_explanation(last_failure),
                    resolution_action=resolution_action,
                    resolution_detail=resolution_detail,
                ))
            failed_iterations.clear()

    return resolutions


def _extract_error_sequences(
    iterations: list[Iteration],
) -> list[ErrorSequence]:
    """Find error→next_error sequences."""
    sequences: list[ErrorSequence] = []
    prev_error_fp: Optional[str] = None
    resolved_last = False

    for it in iterations:
        if not it.result.success:
            error_fp = _error_fingerprint(it)
            if resolved_last and prev_error_fp and error_fp:
                sequences.append(ErrorSequence(
                    device_type=None,
                    os=None,
                    error_fingerprint=prev_error_fp,
                    next_error_fingerprint=error_fp,
                ))
            prev_error_fp = error_fp
            resolved_last = False
        else:
            resolved_last = True

    return sequences


def _error_fingerprint(iteration: Iteration) -> str:
    """Create a normalized error signature."""
    error_text = iteration.result.stderr or iteration.result.error or ""
    # Strip paths, numbers, specific details
    normalized = re.sub(r"/[^\s]+", "<path>", error_text)
    normalized = re.sub(r"\d+\.\d+\.\d+", "<version>", normalized)
    normalized = re.sub(r"0x[0-9a-fA-F]+", "<hex>", normalized)
    normalized = normalized.strip()[:200]
    return hashlib.sha256(normalized.encode()).hexdigest()[:12]


def _categorize_error(iteration: Iteration) -> str:
    """Categorize an error into a broad bucket."""
    error_text = (
        iteration.result.stderr
        or iteration.result.error
        or ""
    ).lower()

    if "permission" in error_text or "errno 13" in error_text:
        return "permissions"
    if "not found" in error_text or "no such" in error_text:
        return "not_found"
    if "timeout" in error_text:
        return "timeout"
    if "no backend" in error_text or "no module" in error_text:
        return "backend"
    if "driver" in error_text:
        return "driver"
    if "busy" in error_text or "in use" in error_text:
        return "resource_busy"
    return "unknown"


def _error_explanation(iteration: Iteration) -> str:
    """Generate a human-readable explanation of the error."""
    error_text = (
        iteration.result.stderr
        or iteration.result.error
        or "Unknown error"
    )
    # Truncate for sharing
    return error_text[:200]
