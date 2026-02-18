"""Tests for the OpenAI provider."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from hardware_agent.core.models import ToolCall
from hardware_agent.core.providers.openai import (
    OpenAIProvider,
    _convert_history,
    _convert_tools,
)


SAMPLE_ANTHROPIC_TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "check_installed",
        "description": "Check package.",
        "input_schema": {
            "type": "object",
            "properties": {"package": {"type": "string"}},
            "required": ["package"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool conversion
# ---------------------------------------------------------------------------

class TestConvertTools:
    def test_converts_to_openai_format(self):
        result = _convert_tools(SAMPLE_ANTHROPIC_TOOLS)
        assert len(result) == 2

        first = result[0]
        assert first["type"] == "function"
        assert first["function"]["name"] == "bash"
        assert first["function"]["description"] == "Run a shell command."
        assert first["function"]["parameters"] == SAMPLE_ANTHROPIC_TOOLS[0]["input_schema"]

    def test_renames_input_schema_to_parameters(self):
        result = _convert_tools(SAMPLE_ANTHROPIC_TOOLS)
        for tool in result:
            assert "input_schema" not in tool["function"]
            assert "parameters" in tool["function"]


# ---------------------------------------------------------------------------
# History conversion
# ---------------------------------------------------------------------------

class TestConvertHistory:
    def test_converts_tool_use_to_tool_calls(self):
        history = [
            {
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": "toolu_001",
                    "name": "bash",
                    "input": {"command": "lsusb"},
                }],
            },
            {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "toolu_001",
                    "content": "Bus 001 Device 003",
                }],
            },
        ]

        result = _convert_history(history)
        assert len(result) == 2

        # Assistant message
        assistant_msg = result[0]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["content"] is None
        assert len(assistant_msg["tool_calls"]) == 1
        tc = assistant_msg["tool_calls"][0]
        assert tc["id"] == "toolu_001"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "bash"
        assert json.loads(tc["function"]["arguments"]) == {"command": "lsusb"}

        # Tool result message
        tool_msg = result[1]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "toolu_001"
        assert tool_msg["content"] == "Bus 001 Device 003"

    def test_empty_history(self):
        assert _convert_history([]) == []

    def test_multiple_iterations(self):
        history = [
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "bash", "input": {"command": "ls"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "file.txt"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t2", "name": "bash", "input": {"command": "cat file.txt"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "hello"}]},
        ]
        result = _convert_history(history)
        assert len(result) == 4


# ---------------------------------------------------------------------------
# OpenAIProvider
# ---------------------------------------------------------------------------

def _mock_openai_response(name: str, arguments: dict, call_id: str = "call_001"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)

    choice = MagicMock()
    choice.message.tool_calls = [tc]

    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_openai_no_tool_response():
    choice = MagicMock()
    choice.message.tool_calls = None

    response = MagicMock()
    response.choices = [choice]
    return response


class TestOpenAIProvider:
    @patch("hardware_agent.core.providers.openai.openai.OpenAI")
    def test_get_next_action_returns_tool_call(self, MockOpenAI):
        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "bash", {"command": "lsusb"}, "call_abc"
        )

        provider = OpenAIProvider("gpt-4o")
        result = provider.get_next_action(
            system_prompt="You are helpful.",
            initial_message="Connect to device.",
            history=[],
            tools=SAMPLE_ANTHROPIC_TOOLS,
        )

        assert isinstance(result, ToolCall)
        assert result.id == "call_abc"
        assert result.name == "bash"
        assert result.parameters == {"command": "lsusb"}

    @patch("hardware_agent.core.providers.openai.openai.OpenAI")
    def test_system_prompt_as_system_message(self, MockOpenAI):
        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "bash", {"command": "ls"}
        )

        provider = OpenAIProvider("gpt-4o")
        provider.get_next_action(
            system_prompt="sys prompt",
            initial_message="initial msg",
            history=[],
            tools=SAMPLE_ANTHROPIC_TOOLS,
        )

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "sys prompt"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "initial msg"

    @patch("hardware_agent.core.providers.openai.openai.OpenAI")
    def test_tool_choice_required(self, MockOpenAI):
        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "bash", {"command": "ls"}
        )

        provider = OpenAIProvider("gpt-4o")
        provider.get_next_action(
            system_prompt="sys",
            initial_message="msg",
            history=[],
            tools=SAMPLE_ANTHROPIC_TOOLS,
        )

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["tool_choice"] == "required"

    @patch("hardware_agent.core.providers.openai.openai.OpenAI")
    def test_raises_on_no_tool_call(self, MockOpenAI):
        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_no_tool_response()

        provider = OpenAIProvider("gpt-4o")
        with pytest.raises(ValueError, match="tool call"):
            provider.get_next_action(
                system_prompt="sys",
                initial_message="msg",
                history=[],
                tools=SAMPLE_ANTHROPIC_TOOLS,
            )

    def test_check_api_key_present(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            has_key, name = OpenAIProvider.check_api_key()
            assert has_key is True
            assert name == "OPENAI_API_KEY"

    def test_check_api_key_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            has_key, name = OpenAIProvider.check_api_key()
            assert has_key is False
            assert name == "OPENAI_API_KEY"
