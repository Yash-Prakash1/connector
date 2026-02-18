"""Tests for provider detection and registry."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from hardware_agent.core.providers import detect_provider, get_provider_class


# ---------------------------------------------------------------------------
# detect_provider
# ---------------------------------------------------------------------------

class TestDetectProvider:
    def test_claude_models(self):
        assert detect_provider("claude-sonnet-4-20250514") == "anthropic"
        assert detect_provider("claude-3-haiku-20240307") == "anthropic"
        assert detect_provider("claude-opus-4-20250514") == "anthropic"

    def test_gpt_models(self):
        assert detect_provider("gpt-4o") == "openai"
        assert detect_provider("gpt-4o-mini") == "openai"
        assert detect_provider("gpt-3.5-turbo") == "openai"

    def test_o_series_models(self):
        assert detect_provider("o1-preview") == "openai"
        assert detect_provider("o1-mini") == "openai"
        assert detect_provider("o3-mini") == "openai"
        assert detect_provider("o4-mini") == "openai"

    def test_gemini_models(self):
        assert detect_provider("gemini-2.5-pro") == "google"
        assert detect_provider("gemini-2.0-flash") == "google"
        assert detect_provider("gemini-1.5-pro") == "google"

    def test_unknown_model_defaults_to_anthropic(self):
        assert detect_provider("some-custom-model") == "anthropic"
        assert detect_provider("mistral-7b") == "anthropic"

    def test_case_insensitive(self):
        assert detect_provider("GPT-4o") == "openai"
        assert detect_provider("Gemini-2.5-pro") == "google"
        assert detect_provider("Claude-sonnet-4-20250514") == "anthropic"


# ---------------------------------------------------------------------------
# get_provider_class
# ---------------------------------------------------------------------------

class TestGetProviderClass:
    def test_anthropic_provider(self):
        from hardware_agent.core.providers.anthropic import AnthropicProvider
        assert get_provider_class("anthropic") is AnthropicProvider

    def test_openai_import_error(self):
        # Remove cached provider module so it re-imports (and fails on openai)
        with patch.dict(
            "sys.modules",
            {"openai": None, "hardware_agent.core.providers.openai": None},
        ):
            with pytest.raises(ImportError, match="OpenAI SDK not installed"):
                get_provider_class("openai")

    def test_google_import_error(self):
        with patch.dict(
            "sys.modules",
            {
                "google": None,
                "google.genai": None,
                "hardware_agent.core.providers.google": None,
            },
        ):
            with pytest.raises(ImportError, match="Google GenAI SDK not installed"):
                get_provider_class("google")

    def test_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider_class("mistral")
