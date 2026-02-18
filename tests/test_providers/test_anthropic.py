"""Tests for the Anthropic provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hardware_agent.core.models import ToolCall
from hardware_agent.core.providers.anthropic import AnthropicProvider


def _mock_tool_use_response(name: str, params: dict, tool_id: str = "toolu_001"):
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = params
    response = MagicMock()
    response.content = [block]
    return response


def _mock_text_response(text: str = "thinking..."):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


SAMPLE_TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
]


class TestAnthropicProvider:
    @patch("hardware_agent.core.providers.anthropic.anthropic.Anthropic")
    def test_get_next_action_returns_tool_call(self, MockAnthropic):
        mock_client = MockAnthropic.return_value
        mock_client.messages.create.return_value = _mock_tool_use_response(
            "bash", {"command": "lsusb"}, "toolu_abc"
        )

        provider = AnthropicProvider("claude-sonnet-4-20250514")
        result = provider.get_next_action(
            system_prompt="You are helpful.",
            initial_message="Connect to device.",
            history=[],
            tools=SAMPLE_TOOLS,
        )

        assert isinstance(result, ToolCall)
        assert result.id == "toolu_abc"
        assert result.name == "bash"
        assert result.parameters == {"command": "lsusb"}

    @patch("hardware_agent.core.providers.anthropic.anthropic.Anthropic")
    def test_passes_system_prompt_and_tools(self, MockAnthropic):
        mock_client = MockAnthropic.return_value
        mock_client.messages.create.return_value = _mock_tool_use_response(
            "bash", {"command": "ls"}
        )

        provider = AnthropicProvider("claude-sonnet-4-20250514")
        provider.get_next_action(
            system_prompt="sys prompt",
            initial_message="initial msg",
            history=[],
            tools=SAMPLE_TOOLS,
        )

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "sys prompt"
        assert call_kwargs["tools"] == SAMPLE_TOOLS
        assert call_kwargs["messages"][0]["content"] == "initial msg"

    @patch("hardware_agent.core.providers.anthropic.anthropic.Anthropic")
    def test_includes_history_in_messages(self, MockAnthropic):
        mock_client = MockAnthropic.return_value
        mock_client.messages.create.return_value = _mock_tool_use_response(
            "bash", {"command": "ls"}
        )

        history = [
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "bash", "input": {"command": "echo hi"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "hi"}]},
        ]

        provider = AnthropicProvider("claude-sonnet-4-20250514")
        provider.get_next_action(
            system_prompt="sys",
            initial_message="initial",
            history=history,
            tools=SAMPLE_TOOLS,
        )

        call_kwargs = mock_client.messages.create.call_args[1]
        # 1 initial + 2 history = 3 messages
        assert len(call_kwargs["messages"]) == 3

    @patch("hardware_agent.core.providers.anthropic.anthropic.Anthropic")
    def test_raises_on_no_tool_use(self, MockAnthropic):
        mock_client = MockAnthropic.return_value
        mock_client.messages.create.return_value = _mock_text_response()

        provider = AnthropicProvider("claude-sonnet-4-20250514")
        with pytest.raises(ValueError, match="tool_use"):
            provider.get_next_action(
                system_prompt="sys",
                initial_message="msg",
                history=[],
                tools=SAMPLE_TOOLS,
            )

    def test_check_api_key_present(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            has_key, name = AnthropicProvider.check_api_key()
            assert has_key is True
            assert name == "ANTHROPIC_API_KEY"

    def test_check_api_key_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            has_key, name = AnthropicProvider.check_api_key()
            assert has_key is False
            assert name == "ANTHROPIC_API_KEY"
