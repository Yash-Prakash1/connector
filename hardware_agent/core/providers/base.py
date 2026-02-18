"""Base class for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from hardware_agent.core.models import ToolCall


class BaseLLMProvider(ABC):
    """Abstract base for LLM provider implementations."""

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    def get_next_action(
        self,
        system_prompt: str,
        initial_message: str,
        history: list[dict],
        tools: list[dict],
    ) -> ToolCall:
        """Call the LLM and return the next tool call.

        Args:
            system_prompt: The full system prompt string.
            initial_message: The initial user message (e.g. "Connect to the ...").
            history: Anthropic-format tool_use/tool_result message pairs.
            tools: Anthropic-format tool definitions (with input_schema).

        Returns:
            A ToolCall extracted from the LLM response.
        """

    @staticmethod
    @abstractmethod
    def check_api_key() -> tuple[bool, str]:
        """Check whether the required API key is set.

        Returns:
            (is_set, env_var_name) — e.g. (True, "ANTHROPIC_API_KEY").
        """
