"""Concrete AI provider implementations.

Each module defines a single :class:`~app.ai.base.AIProvider` subclass. The
:data:`PROVIDER_REGISTRY` maps the short provider name (as used in
``AI_PROVIDER_ORDER``) to its class so the orchestrator can instantiate the
configured chain.
"""

from __future__ import annotations

from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.bedrock import BedrockProvider
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.openai import OpenAIProvider

PROVIDER_REGISTRY = {
    GeminiProvider.name: GeminiProvider,
    BedrockProvider.name: BedrockProvider,
    OpenAIProvider.name: OpenAIProvider,
    AnthropicProvider.name: AnthropicProvider,
}

__all__ = [
    "PROVIDER_REGISTRY",
    "AnthropicProvider",
    "BedrockProvider",
    "GeminiProvider",
    "OpenAIProvider",
]
