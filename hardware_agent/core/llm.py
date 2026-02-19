"""LLM client — provider-agnostic interface for tool_use agents."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Optional

from hardware_agent.core.models import AgentContext, ToolCall
from hardware_agent.core.providers import detect_provider, get_provider_class
from hardware_agent.core.tools import TOOLS, TROUBLESHOOT_TOOLS

if TYPE_CHECKING:
    from hardware_agent.data.community import CommunityKnowledge

_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")


def _load_prompt(name: str) -> str:
    path = os.path.join(_PROMPTS_DIR, name)
    with open(path) as f:
        return f.read()


class LLMClient:
    """Provider-agnostic LLM client for agent decisions."""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.model = model
        provider_name = detect_provider(model)
        provider_class = get_provider_class(provider_name)
        self.provider = provider_class(model)

    def get_next_action(
        self,
        context: AgentContext,
        community_knowledge: Optional[Any] = None,
        loop_breaker: Optional[str] = None,
    ) -> ToolCall:
        """Get the next tool call from the LLM."""
        system_prompt = self._build_system_prompt(
            context, community_knowledge, loop_breaker
        )

        if context.mode == "troubleshoot":
            initial_message = (
                f"The user needs help troubleshooting an issue with their "
                f"{context.device_name} setup. Start by asking what problem "
                f"they're experiencing."
            )
            tools = TROUBLESHOOT_TOOLS
        else:
            initial_message = (
                f"Connect to the {context.device_name}. Once you have a working "
                f"connection, ask the user what they want to accomplish with "
                f"the device, then generate Python code tailored to their goal."
            )
            tools = TOOLS

        history = context.format_history_for_llm()

        return self.provider.get_next_action(
            system_prompt, initial_message, history, tools
        )

    def _build_system_prompt(
        self,
        context: AgentContext,
        community_knowledge: Optional[Any],
        loop_breaker: Optional[str],
    ) -> str:
        if context.mode == "troubleshoot":
            base = _load_prompt("troubleshoot.txt")
        else:
            base = _load_prompt("system.txt")

        # Device context
        if context.device_type == "unknown":
            device_context = (
                "No specific device selected. The user will describe "
                "their setup interactively.\n"
            )
        else:
            device_context = (
                f"Device: {context.device_name} ({context.device_type})\n"
            )
        hints = context.device_hints
        if hints.get("common_errors"):
            device_context += "\nKnown error solutions:\n"
            for err, sol in hints["common_errors"].items():
                device_context += f"  - \"{err}\" → {sol}\n"
        if hints.get("known_quirks"):
            device_context += "\nKnown quirks:\n"
            for q in hints["known_quirks"]:
                device_context += f"  - {q}\n"
        if hints.get("setup_steps"):
            device_context += "\nRecommended setup order:\n"
            for i, step in enumerate(hints["setup_steps"], 1):
                device_context += f"  {i}. {step}\n"
        if hints.get("required_packages"):
            device_context += (
                f"\nRequired packages: {', '.join(hints['required_packages'])}\n"
            )
        os_key = context.environment.os.value
        if hints.get("os_specific", {}).get(os_key):
            device_context += f"\nOS-specific ({os_key}):\n"
            for k, v in hints["os_specific"][os_key].items():
                device_context += f"  {k}: {v}\n"

        # Environment
        env = context.environment
        env_context = (
            f"OS: {env.os.value} ({env.os_version})\n"
            f"Python: {env.python_version} ({env.python_path})\n"
            f"Environment: {env.env_type}"
        )
        if env.env_path:
            env_context += f" ({env.env_path})"
        env_context += "\n"

        relevant_packages = [
            "pyvisa", "pyvisa-py", "pyusb", "pyserial", "libusb",
        ]
        installed = []
        for pkg in relevant_packages:
            version = env.installed_packages.get(pkg)
            if version:
                installed.append(f"  {pkg}: {version}")
        if installed:
            env_context += "Installed packages:\n" + "\n".join(installed) + "\n"
        else:
            env_context += "No relevant packages installed yet.\n"

        if env.is_wsl:
            env_context += "WSL2: yes (Windows Subsystem for Linux)\n"

        if env.usb_devices:
            env_context += f"USB devices detected: {len(env.usb_devices)}\n"
        if env.visa_resources:
            env_context += (
                f"VISA resources: {', '.join(env.visa_resources)}\n"
            )

        # WSL2-specific guidance
        wsl_context = ""
        if env.is_wsl:
            wsl_context = (
                "\n## WSL2 USB Passthrough\n"
                "USB devices are NOT automatically available inside WSL2. "
                "The user must attach them from Windows using usbipd-win.\n"
                "If the device is not visible in lsusb, use ONE ask_user call "
                "to give the user all steps at once:\n"
                "  1. Open PowerShell as Administrator on Windows\n"
                "  2. Run: usbipd list — find the device BUSID\n"
                "  3. Run: usbipd bind --busid <BUSID>\n"
                "  4. Run: usbipd attach --wsl --busid <BUSID>\n"
                "Offer choices like [\"Done\", \"I got an error\", \"usbipd not installed\"].\n"
                "After user confirms, verify with lsusb yourself — NEVER ask "
                "the user to paste command output.\n"
            )

        # Community knowledge
        community_context = ""
        if community_knowledge:
            community_context = self._format_community_knowledge(
                community_knowledge
            )

        # Iteration info
        iteration_context = (
            f"Iteration: {context.get_current_iteration()} / {context.max_iterations}"
        )

        # Build full prompt
        prompt = base.replace("{DEVICE_CONTEXT}", device_context)
        prompt = prompt.replace("{ENVIRONMENT}", env_context + wsl_context)
        prompt = prompt.replace("{COMMUNITY_KNOWLEDGE}", community_context)
        prompt = prompt.replace("{ITERATION}", iteration_context)

        if loop_breaker:
            prompt += f"\n\n{loop_breaker}"

        return prompt

    def _format_community_knowledge(self, data: Any) -> str:
        if not data:
            return ""

        lines = ["COMMUNITY KNOWLEDGE (from successful connections):"]

        patterns = data.get("patterns", [])
        if patterns:
            lines.append("\nTop resolution patterns:")
            for i, p in enumerate(patterns[:5], 1):
                success_rate = p.get("success_rate", 0) * 100
                count = p.get("success_count", 0)
                steps = p.get("steps", [])
                step_desc = ", ".join(
                    s.get("action", "?") for s in steps
                )
                lines.append(
                    f"  {i}. [{success_rate:.0f}% success, {count} uses] "
                    f"{step_desc}"
                )

        errors = data.get("errors", [])
        if errors:
            lines.append("\nKnown error resolutions:")
            for e in errors[:10]:
                lines.append(
                    f"  - \"{e.get('error_fingerprint', '?')}\" → "
                    f"{e.get('resolution_action', '?')} "
                    f"({e.get('success_rate', 0) * 100:.0f}% success)\n"
                    f"    Meaning: {e.get('explanation', 'unknown')}"
                )

        configs = data.get("working_configs", [])
        if configs:
            lines.append("\nKnown working configuration:")
            cfg = configs[0]
            packages = cfg.get("packages", {})
            for pkg, ver in packages.items():
                lines.append(f"  {pkg}: {ver}")

        return "\n".join(lines)
