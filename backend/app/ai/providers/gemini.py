"""Google Gemini provider (Generative Language REST API).

Uses the API key from settings via httpx. HTTP 429 and 5xx and request
timeouts map to :class:`ProviderUnavailable` so the orchestrator falls back to
the next provider. The API key is sent only in the request and never placed on
the returned :class:`AISuggestion`.
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

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_DEFAULT_MODEL = "gemini-1.5-flash"
_TIMEOUT = 30.0


class GeminiProvider(AIProvider):
    """Gemini provider backed by the Generative Language API."""

    name = "gemini"

    def is_configured(self) -> bool:
        return bool(self.settings.GEMINI_API_KEY)

    @property
    def _model(self) -> str:
        return _DEFAULT_MODEL

    async def suggest(self, context: PromptContext) -> AISuggestion:
        prompt = build_prompt(context)
        url = f"{_API_BASE}/{self._model}:generateContent"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        params = {"key": self.settings.GEMINI_API_KEY}

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, json=payload, params=params)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ProviderUnavailable(f"gemini request failed: {type(exc).__name__}") from exc

        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderUnavailable(f"gemini HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ProviderError(f"gemini HTTP {resp.status_code}")

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            # No candidate often means the prompt was blocked by safety filters.
            feedback = data.get("promptFeedback") or {}
            if feedback.get("blockReason"):
                raise ProviderRefusal(f"gemini refused: {feedback.get('blockReason')}")
            raise ProviderError("gemini returned no candidates")

        candidate = candidates[0]
        if candidate.get("finishReason") == "SAFETY":
            raise ProviderRefusal("gemini refused on safety grounds")

        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        if not text.strip():
            raise ProviderError("gemini returned empty content")

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
