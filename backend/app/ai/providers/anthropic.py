"""Anthropic provider (Messages API).

Uses the API key from settings via httpx. HTTP 429 and 5xx and request
timeouts map to :class:`ProviderUnavailable`. The API key is sent only in the
``x-api-key`` header and never placed on the returned :class:`AISuggestion`.
"""

from __future__ import annotations

import httpx

from app.ai.base import (
    AIProvider,
    AISuggestion,
    ProviderError,
    ProviderRefusal,
    ProviderUnavailable,
)
from app.ai.prompt import PromptContext, build_prompt, parse_response

_API_URL = "https://api.anthropic.com/v1/messages"
_DEFAULT_MODEL = "claude-3-5-sonnet-latest"
_API_VERSION = "2023-06-01"
_TIMEOUT = 30.0


class AnthropicProvider(AIProvider):
    """Anthropic provider backed by the Messages API."""

    name = "anthropic"

    def is_configured(self) -> bool:
        return bool(self.settings.ANTHROPIC_API_KEY)

    @property
    def _model(self) -> str:
        return _DEFAULT_MODEL

    async def suggest(self, context: PromptContext) -> AISuggestion:
        prompt = build_prompt(context)
        payload = {
            "model": self._model,
            "max_tokens": 1024,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self.settings.ANTHROPIC_API_KEY,
            "anthropic-version": _API_VERSION,
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(_API_URL, json=payload, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ProviderUnavailable(f"anthropic request failed: {type(exc).__name__}") from exc

        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderUnavailable(f"anthropic HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ProviderError(f"anthropic HTTP {resp.status_code}")

        data = resp.json()
        if data.get("stop_reason") == "refusal":
            raise ProviderRefusal("anthropic refused the request")

        blocks = data.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        if not text.strip():
            raise ProviderError("anthropic returned empty content")

        try:
            suggested_sql, explanation, optimizations = parse_response(text, self.name)
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc

        return AISuggestion(
            suggested_sql=suggested_sql,
            explanation=explanation,
            optimizations=optimizations,
            provider=self.name,
        )
