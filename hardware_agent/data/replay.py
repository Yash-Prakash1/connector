"""Replay engine — replays proven patterns directly without LLM."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from hardware_agent.core.models import ToolCall, ToolResult
from hardware_agent.core.executor import ToolExecutor
from hardware_agent.data.store import DataStore
from hardware_agent.devices.base import DeviceModule

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 5
SUCCESS_RATE_THRESHOLD = 0.9


class ReplayEngine:
    """Attempts to replay a proven pattern directly, without the LLM."""

    def find_replay_candidate(
        self,
        device_type: str,
        os_name: str,
        fingerprint: str,
        store: DataStore,
    ) -> Optional[dict]:
        """Find a high-confidence pattern matching the current situation."""
        patterns = store.get_cached_patterns(device_type, os_name)
        for p in patterns:
            if (
                p.get("success_count", 0) >= CONFIDENCE_THRESHOLD
                and p.get("success_rate", 0) >= SUCCESS_RATE_THRESHOLD
                and (
                    p.get("initial_state_fingerprint") is None
                    or p.get("initial_state_fingerprint") == fingerprint
                )
            ):
                return p
        return None

    def execute_replay(
        self,
        pattern: dict,
        executor: ToolExecutor,
        device_module: DeviceModule,
        os_name: str,
        confirm_callback: Callable[[str], bool],
    ) -> dict:
        """Execute a replay pattern step by step.

        Returns {"success": bool, "steps_executed": int, "failed_at_step": int|None, "error": str|None}
        """
        steps = pattern.get("steps", [])
        if not steps:
            return {
                "success": False,
                "steps_executed": 0,
                "failed_at_step": 0,
                "error": "No steps in pattern",
            }

        for i, step in enumerate(steps):
            tool_call = self._expand_step(step, device_module, os_name)
            if tool_call is None:
                continue

            # Confirm with user
            desc = f"Replay step {i + 1}/{len(steps)}: {tool_call.name}"
            if tool_call.parameters:
                desc += f" ({_summarize_params(tool_call)})"
            if not confirm_callback(desc):
                return {
                    "success": False,
                    "steps_executed": i,
                    "failed_at_step": i,
                    "error": "User declined step",
                }

            result = executor.execute(tool_call)
            if not result.success:
                return {
                    "success": False,
                    "steps_executed": i + 1,
                    "failed_at_step": i,
                    "error": result.error or result.stderr,
                }

        # Verify connection after all steps
        success, message = device_module.verify_connection()
        return {
            "success": success,
            "steps_executed": len(steps),
            "failed_at_step": None if success else len(steps),
            "error": None if success else message,
        }

    def _expand_step(
        self,
        step: dict,
        device_module: DeviceModule,
        os_name: str,
    ) -> Optional[ToolCall]:
        """Convert a normalized step back to an executable ToolCall."""
        action = step.get("action", "")

        if action == "pip_install":
            packages = step.get("packages", [])
            return ToolCall(
                id=f"replay_{action}",
                name="pip_install",
                parameters={"packages": packages},
            )

        elif action == "system_install":
            target = step.get("target", "")
            command = _get_system_install_command(target, os_name)
            if command:
                return ToolCall(
                    id=f"replay_{action}",
                    name="bash",
                    parameters={"command": command},
                )

        elif action == "permission_fix":
            pattern = step.get("pattern", "")
            info = device_module.get_info()
            hints = device_module.get_hints(os_name)
            os_hints = hints.os_specific.get(os_name, {})

            if pattern == "udev_rule":
                udev_rule = os_hints.get("udev_rule", "")
                udev_file = os_hints.get(
                    "udev_file", "/etc/udev/rules.d/99-instrument.rules"
                )
                if udev_rule:
                    command = f"echo '{udev_rule}' | sudo tee {udev_file}"
                    return ToolCall(
                        id=f"replay_{action}",
                        name="bash",
                        parameters={"command": command},
                    )
            elif pattern == "udev_reload":
                reload_cmd = os_hints.get(
                    "udev_reload",
                    "sudo udevadm control --reload-rules && sudo udevadm trigger",
                )
                return ToolCall(
                    id=f"replay_{action}",
                    name="bash",
                    parameters={"command": reload_cmd},
                )

        elif action == "verify":
            pattern = step.get("pattern", "")
            if pattern == "idn_query" or pattern == "device_check":
                return ToolCall(
                    id=f"replay_{action}",
                    name="check_device",
                    parameters={},
                )
            elif pattern == "visa_list":
                return ToolCall(
                    id=f"replay_{action}",
                    name="list_visa_resources",
                    parameters={},
                )
            elif pattern == "usb_list":
                return ToolCall(
                    id=f"replay_{action}",
                    name="list_usb_devices",
                    parameters={},
                )

        return None


def _get_system_install_command(target: str, os_name: str) -> Optional[str]:
    """Map abstract install target to OS-specific command."""
    if target == "libusb":
        if os_name == "linux":
            return "sudo apt install -y libusb-1.0-0-dev"
        elif os_name == "macos":
            return "brew install libusb"
    return None


def _summarize_params(tool_call: ToolCall) -> str:
    """Short summary of tool call parameters."""
    params = tool_call.parameters
    if tool_call.name == "pip_install":
        return ", ".join(params.get("packages", []))
    if tool_call.name == "bash":
        cmd = params.get("command", "")
        return cmd[:60] + "..." if len(cmd) > 60 else cmd
    return ""
