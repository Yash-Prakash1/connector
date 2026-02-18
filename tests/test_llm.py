"""Tests for hardware_agent.core.llm — LLMClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, mock_open

import pytest

from hardware_agent.core.llm import LLMClient, _load_prompt
from hardware_agent.core.models import (
    AgentContext,
    Environment,
    Iteration,
    OS,
    ToolCall,
    ToolResult,
)
from tests.conftest import make_iteration, mock_llm_response


# ---------------------------------------------------------------------------
# Helper: create a mock Anthropic response with NO tool_use block
# ---------------------------------------------------------------------------

def _mock_text_only_response(text="I'm thinking..."):
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text
    response = MagicMock()
    response.content = [text_block]
    return response


# ---------------------------------------------------------------------------
# get_next_action — successful extraction
# ---------------------------------------------------------------------------

class TestGetNextAction:
    @patch("hardware_agent.core.llm._load_prompt")
    @patch("hardware_agent.core.llm.anthropic.Anthropic")
    def test_extracts_tool_call(self, MockAnthropic, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = "system prompt {DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        mock_response = mock_llm_response(
            "check_installed", {"package": "pyvisa"}
        )
        mock_client_instance = MockAnthropic.return_value
        mock_client_instance.messages.create.return_value = mock_response

        llm = LLMClient(model="claude-sonnet-4-20250514")
        result = llm.get_next_action(mock_agent_context)

        assert isinstance(result, ToolCall)
        assert result.name == "check_installed"
        assert result.parameters == {"package": "pyvisa"}
        assert result.id == "toolu_check_installed_001"

    @patch("hardware_agent.core.llm._load_prompt")
    @patch("hardware_agent.core.llm.anthropic.Anthropic")
    def test_passes_community_knowledge(self, MockAnthropic, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = "{DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        mock_response = mock_llm_response("bash", {"command": "lsusb"})
        mock_client_instance = MockAnthropic.return_value
        mock_client_instance.messages.create.return_value = mock_response

        community_data = {
            "patterns": [{"success_rate": 0.9, "success_count": 5, "steps": [{"action": "install pyvisa"}]}],
            "errors": [],
            "working_configs": [],
        }

        llm = LLMClient()
        llm.get_next_action(mock_agent_context, community_knowledge=community_data)

        # Verify messages.create was called
        call_kwargs = mock_client_instance.messages.create.call_args[1]
        system_prompt = call_kwargs["system"]
        assert "COMMUNITY KNOWLEDGE" in system_prompt

    @patch("hardware_agent.core.llm._load_prompt")
    @patch("hardware_agent.core.llm.anthropic.Anthropic")
    def test_appends_loop_breaker(self, MockAnthropic, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = "{DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        mock_response = mock_llm_response("give_up", {"reason": "stuck"})
        mock_client_instance = MockAnthropic.return_value
        mock_client_instance.messages.create.return_value = mock_response

        llm = LLMClient()
        llm.get_next_action(
            mock_agent_context,
            loop_breaker="STOP LOOPING",
        )

        call_kwargs = mock_client_instance.messages.create.call_args[1]
        assert "STOP LOOPING" in call_kwargs["system"]

    @patch("hardware_agent.core.llm._load_prompt")
    @patch("hardware_agent.core.llm.anthropic.Anthropic")
    def test_forwards_tools(self, MockAnthropic, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = "{DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        mock_response = mock_llm_response("bash", {"command": "ls"})
        mock_client_instance = MockAnthropic.return_value
        mock_client_instance.messages.create.return_value = mock_response

        llm = LLMClient()
        llm.get_next_action(mock_agent_context)

        call_kwargs = mock_client_instance.messages.create.call_args[1]
        assert "tools" in call_kwargs
        tool_names = [t["name"] for t in call_kwargs["tools"]]
        assert "bash" in tool_names
        assert "complete" in tool_names
        assert "give_up" in tool_names


# ---------------------------------------------------------------------------
# get_next_action — no tool_use block → ValueError
# ---------------------------------------------------------------------------

class TestGetNextActionNoToolUse:
    @patch("hardware_agent.core.llm._load_prompt")
    @patch("hardware_agent.core.llm.anthropic.Anthropic")
    def test_raises_value_error(self, MockAnthropic, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = "{DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        mock_client_instance = MockAnthropic.return_value
        mock_client_instance.messages.create.return_value = _mock_text_only_response()

        llm = LLMClient()
        with pytest.raises(ValueError, match="tool_use"):
            llm.get_next_action(mock_agent_context)

    @patch("hardware_agent.core.llm._load_prompt")
    @patch("hardware_agent.core.llm.anthropic.Anthropic")
    def test_empty_content_raises(self, MockAnthropic, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = "{DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        response = MagicMock()
        response.content = []
        mock_client_instance = MockAnthropic.return_value
        mock_client_instance.messages.create.return_value = response

        llm = LLMClient()
        with pytest.raises(ValueError):
            llm.get_next_action(mock_agent_context)


# ---------------------------------------------------------------------------
# _build_system_prompt
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    @patch("hardware_agent.core.llm._load_prompt")
    def test_injects_device_context(self, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = (
            "PREFIX {DEVICE_CONTEXT} {ENVIRONMENT} {COMMUNITY_KNOWLEDGE} {ITERATION}"
        )
        llm = LLMClient.__new__(LLMClient)
        llm.model = "test"

        prompt = llm._build_system_prompt(mock_agent_context, None, None)
        assert "Rigol DS1054Z" in prompt
        assert "rigol_ds1054z" in prompt

    @patch("hardware_agent.core.llm._load_prompt")
    def test_injects_environment(self, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = (
            "{DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        )
        llm = LLMClient.__new__(LLMClient)
        llm.model = "test"

        prompt = llm._build_system_prompt(mock_agent_context, None, None)
        assert "linux" in prompt.lower()
        assert "3.12.0" in prompt
        assert "venv" in prompt

    @patch("hardware_agent.core.llm._load_prompt")
    def test_injects_community_knowledge(self, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = (
            "{DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        )
        community_data = {
            "patterns": [
                {
                    "success_rate": 0.95,
                    "success_count": 12,
                    "steps": [{"action": "install pyvisa"}],
                },
            ],
            "errors": [
                {
                    "error_fingerprint": "No backend",
                    "resolution_action": "pip install pyvisa-py",
                    "success_rate": 0.8,
                    "explanation": "Need py backend",
                },
            ],
            "working_configs": [
                {"packages": {"pyvisa": "1.14.0", "pyusb": "1.2.1"}},
            ],
        }
        llm = LLMClient.__new__(LLMClient)
        llm.model = "test"

        prompt = llm._build_system_prompt(mock_agent_context, community_data, None)
        assert "COMMUNITY KNOWLEDGE" in prompt
        assert "install pyvisa" in prompt
        assert "No backend" in prompt
        assert "1.14.0" in prompt

    @patch("hardware_agent.core.llm._load_prompt")
    def test_injects_iteration_count(self, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = (
            "{DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        )
        llm = LLMClient.__new__(LLMClient)
        llm.model = "test"

        prompt = llm._build_system_prompt(mock_agent_context, None, None)
        assert "0 / 20" in prompt

    @patch("hardware_agent.core.llm._load_prompt")
    def test_loop_breaker_appended(self, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = (
            "{DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        )
        llm = LLMClient.__new__(LLMClient)
        llm.model = "test"

        prompt = llm._build_system_prompt(
            mock_agent_context, None, "BREAK THE LOOP"
        )
        assert "BREAK THE LOOP" in prompt

    @patch("hardware_agent.core.llm._load_prompt")
    def test_no_loop_breaker_when_none(self, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = (
            "BASE{DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        )
        llm = LLMClient.__new__(LLMClient)
        llm.model = "test"

        prompt = llm._build_system_prompt(mock_agent_context, None, None)
        assert "BREAK" not in prompt

    @patch("hardware_agent.core.llm._load_prompt")
    def test_device_hints_common_errors(self, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = (
            "{DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        )
        llm = LLMClient.__new__(LLMClient)
        llm.model = "test"

        prompt = llm._build_system_prompt(mock_agent_context, None, None)
        assert "No backend available" in prompt
        assert "Install pyvisa-py" in prompt

    @patch("hardware_agent.core.llm._load_prompt")
    def test_device_hints_known_quirks(self, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = (
            "{DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        )
        llm = LLMClient.__new__(LLMClient)
        llm.model = "test"

        prompt = llm._build_system_prompt(mock_agent_context, None, None)
        assert "USB 3.0 may cause issues" in prompt

    @patch("hardware_agent.core.llm._load_prompt")
    def test_device_hints_required_packages(self, mock_load_prompt, mock_agent_context):
        mock_load_prompt.return_value = (
            "{DEVICE_CONTEXT}{ENVIRONMENT}{COMMUNITY_KNOWLEDGE}{ITERATION}"
        )
        llm = LLMClient.__new__(LLMClient)
        llm.model = "test"

        prompt = llm._build_system_prompt(mock_agent_context, None, None)
        assert "pyvisa" in prompt
        assert "pyusb" in prompt


# ---------------------------------------------------------------------------
# _build_messages
# ---------------------------------------------------------------------------

class TestBuildMessages:
    def test_initial_user_message(self, mock_agent_context):
        llm = LLMClient.__new__(LLMClient)
        llm.model = "test"

        messages = llm._build_messages(mock_agent_context)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "Rigol DS1054Z" in messages[0]["content"]
        assert "Python code" in messages[0]["content"]

    def test_includes_history(self, mock_agent_context):
        # Add some iterations to the context
        mock_agent_context.iterations.append(
            make_iteration(1, "check_installed", {"package": "pyvisa"}, success=False, stdout="pyvisa is NOT installed")
        )
        mock_agent_context.iterations.append(
            make_iteration(2, "pip_install", {"packages": ["pyvisa"]}, success=True, stdout="Successfully installed")
        )

        llm = LLMClient.__new__(LLMClient)
        llm.model = "test"

        messages = llm._build_messages(mock_agent_context)
        # 1 initial user message + 2 iterations * 2 messages each = 5
        assert len(messages) == 5

        # First is user message
        assert messages[0]["role"] == "user"

        # Second is assistant with tool_use
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"][0]["type"] == "tool_use"
        assert messages[1]["content"][0]["name"] == "check_installed"

        # Third is user with tool_result
        assert messages[2]["role"] == "user"
        assert messages[2]["content"][0]["type"] == "tool_result"

    def test_empty_history(self, mock_agent_context):
        llm = LLMClient.__new__(LLMClient)
        llm.model = "test"

        messages = llm._build_messages(mock_agent_context)
        assert len(messages) == 1

    def test_history_error_fields_included(self, mock_agent_context):
        mock_agent_context.iterations.append(
            make_iteration(1, "bash", {"command": "lsusb"}, success=False, stderr="permission denied", error="failed")
        )
        llm = LLMClient.__new__(LLMClient)
        llm.model = "test"

        messages = llm._build_messages(mock_agent_context)
        tool_result_msg = messages[2]
        content_text = tool_result_msg["content"][0]["content"]
        assert "permission denied" in content_text
        assert "failed" in content_text
        assert tool_result_msg["content"][0]["is_error"] is True
