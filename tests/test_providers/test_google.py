"""Tests for the Google Gemini provider."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from hardware_agent.core.models import ToolCall

# Mock google.genai before importing the provider module
_mock_genai = MagicMock()
_mock_types = _mock_genai.types

# Set up the module hierarchy so `from google import genai` works
_mock_google = MagicMock()
_mock_google.genai = _mock_genai

_original_google = sys.modules.get("google")
_original_genai = sys.modules.get("google.genai")
_original_types = sys.modules.get("google.genai.types")

sys.modules["google"] = _mock_google
sys.modules["google.genai"] = _mock_genai
sys.modules["google.genai.types"] = _mock_types

from hardware_agent.core.providers.google import (  # noqa: E402
    GoogleProvider,
    _convert_history,
    _convert_tools,
)

# Restore original modules (if any) after import
if _original_google is not None:
    sys.modules["google"] = _original_google
else:
    sys.modules.pop("google", None)
if _original_genai is not None:
    sys.modules["google.genai"] = _original_genai
else:
    sys.modules.pop("google.genai", None)
if _original_types is not None:
    sys.modules["google.genai.types"] = _original_types
else:
    sys.modules.pop("google.genai.types", None)


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
]


# ---------------------------------------------------------------------------
# Tool conversion
# ---------------------------------------------------------------------------

class TestConvertTools:
    @patch("hardware_agent.core.providers.google.types")
    def test_creates_function_declarations(self, mock_types):
        mock_types.FunctionDeclaration.return_value = "fd_mock"
        mock_types.Tool.return_value = "tool_mock"

        result = _convert_tools(SAMPLE_ANTHROPIC_TOOLS)

        mock_types.FunctionDeclaration.assert_called_once_with(
            name="bash",
            description="Run a shell command.",
            parameters=SAMPLE_ANTHROPIC_TOOLS[0]["input_schema"],
        )
        mock_types.Tool.assert_called_once_with(function_declarations=["fd_mock"])
        assert result == ["tool_mock"]


# ---------------------------------------------------------------------------
# History conversion
# ---------------------------------------------------------------------------

class TestConvertHistory:
    @patch("hardware_agent.core.providers.google.types")
    def test_converts_tool_use_to_function_call(self, mock_types):
        mock_types.Part.from_function_call.return_value = "fc_part"
        mock_types.Content.return_value = "content_mock"

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
        ]

        result = _convert_history(history)

        mock_types.Part.from_function_call.assert_called_once_with(
            name="bash",
            args={"command": "lsusb"},
        )
        mock_types.Content.assert_called_once_with(role="model", parts=["fc_part"])
        assert len(result) == 1

    @patch("hardware_agent.core.providers.google.types")
    def test_converts_tool_result_to_function_response(self, mock_types):
        mock_types.Part.from_function_response.return_value = "fr_part"
        mock_types.Content.return_value = "content_mock"

        history = [
            {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "toolu_001",
                    "_tool_name": "bash",
                    "content": "Bus 001 Device 003",
                }],
            },
        ]

        result = _convert_history(history)

        mock_types.Part.from_function_response.assert_called_once_with(
            name="bash",
            response={"result": "Bus 001 Device 003"},
        )
        assert len(result) == 1

    @patch("hardware_agent.core.providers.google.types")
    def test_empty_history(self, mock_types):
        assert _convert_history([]) == []


# ---------------------------------------------------------------------------
# GoogleProvider
# ---------------------------------------------------------------------------

class TestGoogleProvider:
    @patch("hardware_agent.core.providers.google.types")
    @patch("hardware_agent.core.providers.google.genai.Client")
    def test_get_next_action_returns_tool_call(self, MockClient, mock_types):
        fc = MagicMock()
        fc.name = "bash"
        fc.args = {"command": "lsusb"}

        part = MagicMock()
        part.function_call = fc

        candidate = MagicMock()
        candidate.content.parts = [part]

        response = MagicMock()
        response.candidates = [candidate]

        mock_client = MockClient.return_value
        mock_client.models.generate_content.return_value = response

        mock_types.FunctionDeclaration.return_value = "fd_mock"
        mock_types.Tool.return_value = "tool_mock"
        mock_types.Content.return_value = MagicMock()
        mock_types.Part.from_text.return_value = MagicMock()
        mock_types.GenerateContentConfig.return_value = "config_mock"
        mock_types.ToolConfig.return_value = "tc_mock"
        mock_types.FunctionCallingConfig.return_value = "fcc_mock"

        provider = GoogleProvider("gemini-2.5-pro")
        result = provider.get_next_action(
            system_prompt="You are helpful.",
            initial_message="Connect to device.",
            history=[],
            tools=SAMPLE_ANTHROPIC_TOOLS,
        )

        assert isinstance(result, ToolCall)
        assert result.name == "bash"
        assert result.parameters == {"command": "lsusb"}
        assert result.id.startswith("gemini_")

    @patch("hardware_agent.core.providers.google.types")
    @patch("hardware_agent.core.providers.google.genai.Client")
    def test_raises_on_no_function_call(self, MockClient, mock_types):
        part = MagicMock()
        part.function_call = None

        candidate = MagicMock()
        candidate.content.parts = [part]

        response = MagicMock()
        response.candidates = [candidate]

        mock_client = MockClient.return_value
        mock_client.models.generate_content.return_value = response

        mock_types.FunctionDeclaration.return_value = "fd_mock"
        mock_types.Tool.return_value = "tool_mock"
        mock_types.Content.return_value = MagicMock()
        mock_types.Part.from_text.return_value = MagicMock()
        mock_types.GenerateContentConfig.return_value = "config_mock"
        mock_types.ToolConfig.return_value = "tc_mock"
        mock_types.FunctionCallingConfig.return_value = "fcc_mock"

        provider = GoogleProvider("gemini-2.5-pro")
        with pytest.raises(ValueError, match="function call"):
            provider.get_next_action(
                system_prompt="sys",
                initial_message="msg",
                history=[],
                tools=SAMPLE_ANTHROPIC_TOOLS,
            )

    def test_check_api_key_present(self):
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "aig-test"}):
            has_key, name = GoogleProvider.check_api_key()
            assert has_key is True
            assert name == "GOOGLE_API_KEY"

    def test_check_api_key_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            has_key, name = GoogleProvider.check_api_key()
            assert has_key is False
            assert name == "GOOGLE_API_KEY"
