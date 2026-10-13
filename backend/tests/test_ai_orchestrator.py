"""Orchestrator and API-integration tests.

These use fake in-process providers (no HTTP, no network, no keys) to prove the
fallback semantics, and exercise the ``/api/optimize`` endpoint to confirm the
AI suggestion is re-validated by the deterministic validator and that AI is
best-effort (never blocks the rule-based result).
"""

from __future__ import annotations

import pytest

from app.ai.base import (
    AIProvider,
    AISuggestion,
    AllProvidersUnavailable,
    ProviderRefusal,
    ProviderUnavailable,
)
from app.ai.orchestrator import AIOrchestrator
from app.ai.prompt import PromptContext


class FakeProvider(AIProvider):
    """A configurable in-process provider for orchestrator tests."""

    def __init__(
        self,
        name: str,
        *,
        configured: bool = True,
        raises: Exception | None = None,
        suggestion: AISuggestion | None = None,
    ) -> None:
        self.name = name
        self._configured = configured
        self._raises = raises
        self._suggestion = suggestion
        self.calls = 0

    def is_configured(self) -> bool:
        return self._configured

    async def suggest(self, context: PromptContext) -> AISuggestion:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        assert self._suggestion is not None
        return self._suggestion


@pytest.fixture
def context() -> PromptContext:
    return PromptContext(sql="SELECT 1", dialect="postgres")


def _make(providers: list[AIProvider]) -> AIOrchestrator:
    # Pass providers explicitly so no real Settings-based chain is built.
    orch = AIOrchestrator.__new__(AIOrchestrator)
    orch.settings = None  # type: ignore[assignment]
    orch._providers = providers
    return orch


async def test_fallback_on_provider_unavailable(context: PromptContext) -> None:
    first = FakeProvider("first", raises=ProviderUnavailable("429"))
    served = AISuggestion(suggested_sql="SELECT 1", provider="second")
    second = FakeProvider("second", suggestion=served)
    orch = _make([first, second])

    result = await orch.suggest(context)

    assert result.provider == "second"
    assert first.calls == 1
    assert second.calls == 1


async def test_refusal_does_not_fall_back(context: PromptContext) -> None:
    first = FakeProvider("first", raises=ProviderRefusal("safety"))
    served = AISuggestion(suggested_sql="SELECT 1", provider="second")
    second = FakeProvider("second", suggestion=served)
    orch = _make([first, second])

    with pytest.raises(ProviderRefusal):
        await orch.suggest(context)

    assert first.calls == 1
    assert second.calls == 0  # fallback must NOT occur on a refusal


async def test_unconfigured_providers_are_skipped(context: PromptContext) -> None:
    skipped = FakeProvider("skipped", configured=False)
    served = AISuggestion(suggested_sql="SELECT 1", provider="live")
    live = FakeProvider("live", suggestion=served)
    orch = _make([skipped, live])

    result = await orch.suggest(context)

    assert result.provider == "live"
    assert skipped.calls == 0
    assert live.calls == 1


async def test_all_unavailable_raises(context: PromptContext) -> None:
    first = FakeProvider("first", raises=ProviderUnavailable("timeout"))
    second = FakeProvider("second", raises=ProviderUnavailable("500"))
    orch = _make([first, second])

    with pytest.raises(AllProvidersUnavailable):
        await orch.suggest(context)


async def test_none_configured_raises(context: PromptContext) -> None:
    orch = _make([FakeProvider("a", configured=False)])
    with pytest.raises(AllProvidersUnavailable):
        await orch.suggest(context)


def test_build_providers_from_order_skips_unknown() -> None:
    from app.config import Settings

    settings = Settings(AI_PROVIDER_ORDER="gemini,notaprovider,openai")
    orch = AIOrchestrator(settings=settings)
    names = [p.name for p in orch._providers]
    assert names == ["gemini", "openai"]
    # Nothing is configured in the test settings, so none are usable.
    assert orch.configured_providers() == []


# -- API integration: AI re-validation and best-effort behavior ---------------


def _auth_headers(signer) -> dict[str, str]:
    return {"Authorization": f"Bearer {signer.sign(sub='user-ai')}"}


def _install_fake_orchestrator(app, providers: list[AIProvider]) -> None:
    app.state.ai_orchestrator = _make(providers)


def test_optimize_ai_valid_suggestion_is_marked_valid(client, app, signer) -> None:
    good = AISuggestion(
        suggested_sql="SELECT id, email FROM users",
        explanation="Explicit columns.",
        optimizations=["Avoid SELECT *"],
        provider="fake",
    )
    _install_fake_orchestrator(app, [FakeProvider("fake", suggestion=good)])

    resp = client.post(
        "/api/optimize",
        json={"sql": "SELECT * FROM users", "dialect": "postgres", "use_ai": True},
        headers=_auth_headers(signer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ai_available"] is True
    assert body["provider"] == "fake"
    assert body["suggested_sql"] == "SELECT id, email FROM users"
    assert body["is_suggestion_valid"] is True


def test_optimize_ai_bad_sql_is_revalidated_false(client, app, signer) -> None:
    # Suggestion references an unknown table; the deterministic validator must
    # flag it so is_suggestion_valid is False even though AI returned it.
    bad = AISuggestion(
        suggested_sql="SELECT * FROM not_a_real_table",
        provider="fake",
    )
    _install_fake_orchestrator(app, [FakeProvider("fake", suggestion=bad)])

    # connection_id is needed so a schema is loaded for schema validation.
    create = client.post(
        "/api/connections/test",
        json={
            "dialect": "postgres",
            "host": "db.example.com",
            "port": 5432,
            "database": "testdb",
            "username": "reader",
            "password": "super-secret-pw",
        },
        headers=_auth_headers(signer),
    )
    assert create.status_code == 200
    connection_id = create.json()["connection"]["connection_id"]

    resp = client.post(
        "/api/optimize",
        json={
            "sql": "SELECT * FROM users",
            "dialect": "postgres",
            "use_ai": True,
            "connection_id": connection_id,
        },
        headers=_auth_headers(signer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ai_available"] is True
    assert body["suggested_sql"] == "SELECT * FROM not_a_real_table"
    assert body["is_suggestion_valid"] is False


def test_optimize_ai_unavailable_does_not_block_rule_based(client, app, signer) -> None:
    down = FakeProvider("down", raises=ProviderUnavailable("all down"))
    _install_fake_orchestrator(app, [down])

    resp = client.post(
        "/api/optimize",
        json={"sql": "SELECT * FROM users", "dialect": "postgres", "use_ai": True},
        headers=_auth_headers(signer),
    )
    assert resp.status_code == 200
    body = resp.json()
    # Deterministic result still present; AI flagged unavailable.
    assert body["ai_available"] is False
    assert body["ai_message"]
    assert body["suggested_sql"] is None
    assert isinstance(body["optimizations"], list)


def test_optimize_without_use_ai_skips_ai(client, app, signer) -> None:
    # No orchestrator installed; use_ai False must not touch AI at all.
    resp = client.post(
        "/api/optimize",
        json={"sql": "SELECT * FROM users", "dialect": "postgres", "use_ai": False},
        headers=_auth_headers(signer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ai_available"] is False
    assert body["suggested_sql"] is None
