"""OpenAI LLM provider."""

from __future__ import annotations

import json
import os

import openai

from hardware_agent.core.models import ToolCall
from hardware_agent.core.providers.base import BaseLLMProvider


def _convert_tools(anthropic_tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool format to OpenAI function-calling format."""
    result = []
    for tool in anthropic_tools:
        result.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool["input_schema"],
            },
        })
    return result


def _convert_history(anthropic_history: list[dict]) -> list[dict]:
    """Convert Anthropic tool_use/tool_result pairs to OpenAI format."""
    messages = []
    for msg in anthropic_history:
        role = msg["role"]
        content = msg.get("content", [])

        if role == "assistant" and isinstance(content, list):
            # Anthropic tool_use block → OpenAI assistant with tool_calls
            tool_calls = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block["input"]),
                        },
                    })
            if tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls,
                })

        elif role == "user" and isinstance(content, list):
            # Anthropic tool_result block → OpenAI tool message
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    messages.append({
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": block.get("content", ""),
                    })

    return messages


class OpenAIProvider(BaseLLMProvider):
    """Provider for OpenAI models (GPT-4o, o1, o3, etc.)."""

    def __init__(self, model: str):
        super().__init__(model)
        self.client = openai.OpenAI()

    def get_next_action(
        self,
        system_prompt: str,
        initial_message: str,
        history: list[dict],
        tools: list[dict],
    ) -> ToolCall:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": initial_message},
        ]
        messages.extend(_convert_history(history))

        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            tools=_convert_tools(tools),
            tool_choice="required",
            messages=messages,
        )

        choice = response.choices[0].message
        if choice.tool_calls:
            tc = choice.tool_calls[0]
            return ToolCall(
                id=tc.id,
                name=tc.function.name,
                parameters=json.loads(tc.function.arguments),
            )

        raise ValueError(
            "OpenAI response did not contain a tool call. "
            "Response: " + str(choice)
        )

    @staticmethod
    def check_api_key() -> tuple[bool, str]:
        return bool(os.environ.get("OPENAI_API_KEY")), "OPENAI_API_KEY"
