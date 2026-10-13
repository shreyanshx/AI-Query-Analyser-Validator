"""OpenAI provider (Chat Completions API).

Uses the API key from settings via httpx. HTTP 429 and 5xx and request
timeouts map to :class:`ProviderUnavailable`. The API key is sent only as a
bearer header and never placed on the returned :class:`AISuggestion`.
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

_API_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-4o-mini"
_TIMEOUT = 30.0


class OpenAIProvider(AIProvider):
    """OpenAI provider backed by the Chat Completions API."""

    name = "openai"

    def is_configured(self) -> bool:
        return bool(self.settings.OPENAI_API_KEY)

    @property
    def _model(self) -> str:
        return _DEFAULT_MODEL

    async def suggest(self, context: PromptContext) -> AISuggestion:
        prompt = build_prompt(context)
        payload = {
            "model": self._model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"Authorization": f"Bearer {self.settings.OPENAI_API_KEY}"}

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(_API_URL, json=payload, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ProviderUnavailable(f"openai request failed: {type(exc).__name__}") from exc

        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderUnavailable(f"openai HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ProviderError(f"openai HTTP {resp.status_code}")

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("openai returned no choices")

        choice = choices[0]
        if choice.get("finish_reason") == "content_filter":
            raise ProviderRefusal("openai refused on content filter")

        message = choice.get("message") or {}
        text = message.get("content") or ""
        if not text.strip():
            raise ProviderError("openai returned empty content")

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
