"""AI provider orchestration with a configurable fallback chain.

The orchestrator reads ``AI_PROVIDER_ORDER`` (default
``gemini,bedrock,openai,anthropic``), instantiates the configured providers,
and iterates them in order:

* unconfigured providers are skipped,
* a :class:`ProviderUnavailable` moves on to the next provider,
* a :class:`ProviderRefusal` or :class:`ProviderError` STOPS the chain (we do
  not route around a safety refusal or hide a defect), and
* if no provider is configured or every configured one was unavailable,
  :class:`AllProvidersUnavailable` is raised so the API can degrade gracefully.

Credentials are read from settings / IAM by the providers themselves; the
orchestrator never handles or logs them.
"""

from __future__ import annotations

from app.ai.base import (
    AIProvider,
    AISuggestion,
    AllProvidersUnavailable,
    ProviderUnavailable,
)
from app.ai.prompt import PromptContext
from app.ai.providers import PROVIDER_REGISTRY
from app.config import Settings, get_settings
from app.logging_utils import get_logger

logger = get_logger(__name__)


class AIOrchestrator:
    """Iterates the configured provider fallback chain."""

    def __init__(
        self,
        settings: Settings | None = None,
        providers: list[AIProvider] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._providers = providers if providers is not None else self._build_providers()

    def _build_providers(self) -> list[AIProvider]:
        """Instantiate providers named in ``AI_PROVIDER_ORDER``."""
        providers: list[AIProvider] = []
        for name in self.settings.ai_provider_order_list:
            provider_cls = PROVIDER_REGISTRY.get(name.lower())
            if provider_cls is None:
                logger.warning("Unknown AI provider in order: %s", name)
                continue
            providers.append(provider_cls(self.settings))
        return providers

    def configured_providers(self) -> list[AIProvider]:
        """Return the ordered subset of providers that are configured."""
        return [p for p in self._providers if p.is_configured()]

    async def suggest(self, context: PromptContext) -> AISuggestion:
        """Return the first suggestion from the fallback chain.

        Raises :class:`AllProvidersUnavailable` when nothing is configured or
        every configured provider was transiently unavailable. A refusal or a
        hard provider error propagates and stops the chain.
        """
        attempted = False
        for provider in self._providers:
            if not provider.is_configured():
                logger.info("Skipping unconfigured AI provider: %s", provider.name)
                continue
            attempted = True
            try:
                suggestion = await provider.suggest(context)
            except ProviderUnavailable as exc:
                logger.warning("Provider %s unavailable, falling back: %s", provider.name, exc)
                continue
            # Refusal / ProviderError intentionally propagate (no fallback).
            logger.info("AI suggestion served by provider: %s", provider.name)
            return suggestion

        if not attempted:
            raise AllProvidersUnavailable("No AI provider is configured")
        raise AllProvidersUnavailable("All configured AI providers are currently unavailable")
