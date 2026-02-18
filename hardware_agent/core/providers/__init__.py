"""Provider detection and registry for multi-LLM support."""

from __future__ import annotations

from typing import Type

from hardware_agent.core.providers.base import BaseLLMProvider


def detect_provider(model: str) -> str:
    """Detect the provider name from a model string.

    Returns "anthropic", "openai", or "google".
    """
    model_lower = model.lower()

    # OpenAI models
    if any(model_lower.startswith(p) for p in ("gpt-", "o1-", "o3-", "o4-")):
        return "openai"

    # Google Gemini models
    if model_lower.startswith("gemini-"):
        return "google"

    # Default to Anthropic (claude-* and anything unknown)
    return "anthropic"


def get_provider_class(name: str) -> Type[BaseLLMProvider]:
    """Return the provider class for the given provider name.

    Lazy-imports so optional SDKs (openai, google-genai) are only
    loaded when actually needed.

    Raises:
        ImportError: If the required SDK is not installed.
        ValueError: If the provider name is unknown.
    """
    if name == "anthropic":
        from hardware_agent.core.providers.anthropic import AnthropicProvider
        return AnthropicProvider

    if name == "openai":
        try:
            from hardware_agent.core.providers.openai import OpenAIProvider
        except ImportError:
            raise ImportError(
                "OpenAI SDK not installed. Install it with: "
                "pip install hardware-connector[openai]"
            )
        return OpenAIProvider

    if name == "google":
        try:
            from hardware_agent.core.providers.google import GoogleProvider
        except ImportError:
            raise ImportError(
                "Google GenAI SDK not installed. Install it with: "
                "pip install hardware-connector[google]"
            )
        return GoogleProvider

    raise ValueError(f"Unknown provider: {name!r}")
