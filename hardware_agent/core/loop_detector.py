"""Loop detector — prevents the agent from repeating failed actions."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass

from hardware_agent.core.models import ToolCall, ToolResult


@dataclass
class LoopWarning:
    is_loop: bool
    message: str = ""


class LoopDetector:
    """Detects when the agent is stuck repeating the same failed action."""

    def __init__(self, max_repeats: int = 2, history_size: int = 10):
        self.max_repeats = max_repeats
        self.history_size = history_size
        self._action_error_counts: dict[str, int] = defaultdict(int)
        self._history: list[str] = []

    def check(self, tool_call: ToolCall, result: ToolResult) -> LoopWarning:
        """Check if we're in a loop after executing a tool call."""
        if result.success:
            return LoopWarning(is_loop=False)

        action_sig = self._hash_action(tool_call)
        error_sig = self._hash_error(result)
        pair_key = f"{action_sig}:{error_sig}"

        self._action_error_counts[pair_key] += 1
        self._history.append(pair_key)
        if len(self._history) > self.history_size:
            self._history = self._history[-self.history_size:]

        count = self._action_error_counts[pair_key]
        if count >= self.max_repeats:
            return LoopWarning(
                is_loop=True,
                message=(
                    f"Action '{tool_call.name}' has failed with the same error "
                    f"{count} times. Try a completely different approach."
                ),
            )
        return LoopWarning(is_loop=False)

    def get_loop_breaker_message(self) -> str:
        """Return text to inject into the next LLM call when looping."""
        return (
            "IMPORTANT: You are repeating the same action with the same error. "
            "You MUST try a completely different approach. Do NOT retry the same "
            "command. Consider:\n"
            "- A different diagnostic command to understand the root cause\n"
            "- A different installation method or package\n"
            "- Checking system-level prerequisites\n"
            "- A completely different strategy to connect to the device\n"
            "- Using give_up if you've exhausted all options"
        )

    @staticmethod
    def _hash_action(tool_call: ToolCall) -> str:
        data = json.dumps(
            {"name": tool_call.name, "params": tool_call.parameters},
            sort_keys=True,
        )
        return hashlib.sha256(data.encode()).hexdigest()[:12]

    @staticmethod
    def _hash_error(result: ToolResult) -> str:
        error_text = result.stderr or result.error or result.output
        return hashlib.sha256(error_text.encode()).hexdigest()[:12]
