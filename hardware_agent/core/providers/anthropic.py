"""Anthropic (Claude) LLM provider."""

from __future__ import annotations

import os

import anthropic

from hardware_agent.core.models import ToolCall
from hardware_agent.core.providers.base import BaseLLMProvider


class AnthropicProvider(BaseLLMProvider):
    """Provider for Anthropic Claude models."""

    def __init__(self, model: str):
        super().__init__(model)
        self.client = anthropic.Anthropic()

    def get_next_action(
        self,
        system_prompt: str,
        initial_message: str,
        history: list[dict],
        tools: list[dict],
    ) -> ToolCall:
        messages = [{"role": "user", "content": initial_message}]
        messages.extend(history)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        for block in response.content:
            if block.type == "tool_use":
                return ToolCall(
                    id=block.id,
                    name=block.name,
                    parameters=block.input,
                )

        raise ValueError(
            "LLM response did not contain a tool_use block. "
            "Response: " + str(response.content)
        )

    @staticmethod
    def check_api_key() -> tuple[bool, str]:
        return bool(os.environ.get("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY"
