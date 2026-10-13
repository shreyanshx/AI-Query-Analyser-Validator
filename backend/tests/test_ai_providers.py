"""Provider-level tests.

All HTTP is mocked with respx and Bedrock is driven through a stubbed boto3
client, so these tests make no network calls and need no real API keys. They
assert that:

* a 200 JSON body is parsed into an :class:`AISuggestion`,
* a 429 raises :class:`ProviderUnavailable`,
* the API key is read from settings and never appears in the suggestion.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.ai.base import AISuggestion, ProviderError, ProviderUnavailable
from app.ai.prompt import PromptContext
from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.bedrock import BedrockProvider
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.openai import OpenAIProvider
from app.config import Settings

GEMINI_KEY = "gemini-secret-key-xyz"
OPENAI_KEY = "openai-secret-key-xyz"
ANTHROPIC_KEY = "anthropic-secret-key-xyz"

_MODEL_JSON = json.dumps(
    {
        "suggested_sql": "SELECT id, email FROM users WHERE id = 1",
        "explanation": "Replaced SELECT * with explicit columns.",
        "optimizations": ["Avoid SELECT *"],
    }
)


@pytest.fixture
def context() -> PromptContext:
    return PromptContext(sql="SELECT * FROM users WHERE id = 1", dialect="postgres")


def _gemini_body() -> dict:
    return {"candidates": [{"content": {"parts": [{"text": _MODEL_JSON}]}}]}


def _openai_body() -> dict:
    return {"choices": [{"message": {"content": _MODEL_JSON}, "finish_reason": "stop"}]}


def _anthropic_body() -> dict:
    return {"content": [{"type": "text", "text": _MODEL_JSON}], "stop_reason": "end_turn"}


# -- Gemini -------------------------------------------------------------------


@respx.mock
async def test_gemini_success_parses_suggestion(context: PromptContext) -> None:
    settings = Settings(GEMINI_API_KEY=GEMINI_KEY)
    route = respx.post(url__regex=r"https://generativelanguage\.googleapis\.com/.*").mock(
        return_value=httpx.Response(200, json=_gemini_body())
    )

    provider = GeminiProvider(settings)
    assert provider.is_configured() is True
    suggestion = await provider.suggest(context)

    assert isinstance(suggestion, AISuggestion)
    assert suggestion.provider == "gemini"
    assert "users" in suggestion.suggested_sql
    assert suggestion.optimizations == ["Avoid SELECT *"]

    # The API key must be sent in the request but never leak into the result.
    sent_url = str(route.calls.last.request.url)
    assert GEMINI_KEY in sent_url
    assert GEMINI_KEY not in suggestion.model_dump_json()


@respx.mock
async def test_gemini_429_raises_unavailable(context: PromptContext) -> None:
    settings = Settings(GEMINI_API_KEY=GEMINI_KEY)
    respx.post(url__regex=r"https://generativelanguage\.googleapis\.com/.*").mock(
        return_value=httpx.Response(429, json={"error": "rate limited"})
    )
    provider = GeminiProvider(settings)
    with pytest.raises(ProviderUnavailable):
        await provider.suggest(context)


@respx.mock
async def test_gemini_500_raises_unavailable(context: PromptContext) -> None:
    settings = Settings(GEMINI_API_KEY=GEMINI_KEY)
    respx.post(url__regex=r"https://generativelanguage\.googleapis\.com/.*").mock(
        return_value=httpx.Response(503, json={"error": "unavailable"})
    )
    provider = GeminiProvider(settings)
    with pytest.raises(ProviderUnavailable):
        await provider.suggest(context)


def test_gemini_not_configured_without_key() -> None:
    assert GeminiProvider(Settings(GEMINI_API_KEY="")).is_configured() is False


# -- OpenAI -------------------------------------------------------------------


@respx.mock
async def test_openai_success_parses_suggestion(context: PromptContext) -> None:
    settings = Settings(OPENAI_API_KEY=OPENAI_KEY)
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_openai_body())
    )

    provider = OpenAIProvider(settings)
    assert provider.is_configured() is True
    suggestion = await provider.suggest(context)

    assert suggestion.provider == "openai"
    assert "users" in suggestion.suggested_sql

    # Key is sent as a bearer header, never present in the suggestion.
    auth_header = route.calls.last.request.headers.get("authorization")
    assert auth_header == f"Bearer {OPENAI_KEY}"
    assert OPENAI_KEY not in suggestion.model_dump_json()


@respx.mock
async def test_openai_429_raises_unavailable(context: PromptContext) -> None:
    settings = Settings(OPENAI_API_KEY=OPENAI_KEY)
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": "rate limited"})
    )
    provider = OpenAIProvider(settings)
    with pytest.raises(ProviderUnavailable):
        await provider.suggest(context)


@respx.mock
async def test_openai_400_raises_provider_error(context: PromptContext) -> None:
    settings = Settings(OPENAI_API_KEY=OPENAI_KEY)
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(400, json={"error": "bad request"})
    )
    provider = OpenAIProvider(settings)
    with pytest.raises(ProviderError):
        await provider.suggest(context)


# -- Anthropic ----------------------------------------------------------------


@respx.mock
async def test_anthropic_success_and_key_hidden(context: PromptContext) -> None:
    settings = Settings(ANTHROPIC_API_KEY=ANTHROPIC_KEY)
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=_anthropic_body())
    )
    provider = AnthropicProvider(settings)
    suggestion = await provider.suggest(context)

    assert suggestion.provider == "anthropic"
    assert route.calls.last.request.headers.get("x-api-key") == ANTHROPIC_KEY
    assert ANTHROPIC_KEY not in suggestion.model_dump_json()


# -- Bedrock (stubbed boto3) --------------------------------------------------


class _FakeBody:
    def __init__(self, payload: dict) -> None:
        self._data = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._data


class _FakeBedrockClient:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error
        self.called_with: dict | None = None

    def invoke_model(self, **kwargs):
        self.called_with = kwargs
        if self._error is not None:
            raise self._error
        return {"body": _FakeBody(self._payload)}


def _bedrock_settings() -> Settings:
    return Settings(BEDROCK_REGION="us-east-1", BEDROCK_MODEL_ID="anthropic.claude-3-sonnet")


async def test_bedrock_success_with_stubbed_client(
    context: PromptContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {"content": [{"type": "text", "text": _MODEL_JSON}], "stop_reason": "end_turn"}
    fake = _FakeBedrockClient(payload=payload)

    provider = BedrockProvider(_bedrock_settings())
    assert provider.is_configured() is True
    monkeypatch.setattr(provider, "_client", lambda: fake)

    suggestion = await provider.suggest(context)
    assert suggestion.provider == "bedrock"
    assert "users" in suggestion.suggested_sql
    # No static API key is involved; the model id is passed through.
    assert fake.called_with["modelId"] == "anthropic.claude-3-sonnet"


async def test_bedrock_throttling_raises_unavailable(
    context: PromptContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from botocore.exceptions import ClientError

    error = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}},
        "InvokeModel",
    )
    fake = _FakeBedrockClient(error=error)
    provider = BedrockProvider(_bedrock_settings())
    monkeypatch.setattr(provider, "_client", lambda: fake)

    with pytest.raises(ProviderUnavailable):
        await provider.suggest(context)


async def test_bedrock_access_denied_raises_provider_error(
    context: PromptContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from botocore.exceptions import ClientError

    error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "nope"}},
        "InvokeModel",
    )
    fake = _FakeBedrockClient(error=error)
    provider = BedrockProvider(_bedrock_settings())
    monkeypatch.setattr(provider, "_client", lambda: fake)

    with pytest.raises(ProviderError):
        await provider.suggest(context)


def test_bedrock_not_configured_without_region_or_model() -> None:
    assert (
        BedrockProvider(Settings(BEDROCK_REGION="", BEDROCK_MODEL_ID="")).is_configured() is False
    )
    assert (
        BedrockProvider(Settings(BEDROCK_REGION="us-east-1", BEDROCK_MODEL_ID="")).is_configured()
        is False
    )
