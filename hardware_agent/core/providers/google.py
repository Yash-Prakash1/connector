"""Google Gemini LLM provider."""

from __future__ import annotations

import os
import uuid

from google import genai
from google.genai import types

from hardware_agent.core.models import ToolCall
from hardware_agent.core.providers.base import BaseLLMProvider


def _convert_tools(anthropic_tools: list[dict]) -> list[types.Tool]:
    """Convert Anthropic tool format to Gemini FunctionDeclaration objects."""
    declarations = []
    for tool in anthropic_tools:
        schema = tool["input_schema"].copy()
        # Gemini doesn't accept the top-level 'type' on the schema wrapper
        # when passed as a dict; we pass it through directly and let the SDK handle it.
        declarations.append(types.FunctionDeclaration(
            name=tool["name"],
            description=tool.get("description", ""),
            parameters=schema,
        ))
    return [types.Tool(function_declarations=declarations)]


def _convert_history(anthropic_history: list[dict]) -> list[types.Content]:
    """Convert Anthropic tool_use/tool_result pairs to Gemini Content objects."""
    contents = []
    for msg in anthropic_history:
        role = msg["role"]
        content = msg.get("content", [])

        if role == "assistant" and isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    parts.append(types.Part.from_function_call(
                        name=block["name"],
                        args=block["input"],
                    ))
            if parts:
                contents.append(types.Content(role="model", parts=parts))

        elif role == "user" and isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    result_content = block.get("content", "")
                    parts.append(types.Part.from_function_response(
                        name=block.get("_tool_name", "unknown"),
                        response={"result": result_content},
                    ))
            if parts:
                contents.append(types.Content(role="user", parts=parts))

    return contents


class GoogleProvider(BaseLLMProvider):
    """Provider for Google Gemini models."""

    def __init__(self, model: str):
        super().__init__(model)
        self.client = genai.Client()

    def get_next_action(
        self,
        system_prompt: str,
        initial_message: str,
        history: list[dict],
        tools: list[dict],
    ) -> ToolCall:
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=initial_message)],
            ),
        ]
        contents.extend(_convert_history(history))

        gemini_tools = _convert_tools(tools)

        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=gemini_tools,
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="ANY",
                    ),
                ),
            ),
        )

        # Extract function call from response
        for part in response.candidates[0].content.parts:
            if part.function_call:
                fc = part.function_call
                return ToolCall(
                    id=f"gemini_{uuid.uuid4().hex[:12]}",
                    name=fc.name,
                    parameters=dict(fc.args) if fc.args else {},
                )

        raise ValueError(
            "Gemini response did not contain a function call. "
            "Response: " + str(response)
        )

    @staticmethod
    def check_api_key() -> tuple[bool, str]:
        return bool(os.environ.get("GOOGLE_API_KEY")), "GOOGLE_API_KEY"
