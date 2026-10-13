"""Route-level tests for /api/validate and /api/optimize.

These confirm the routers are wired behind ``get_current_user`` and return the
deterministic engine's output. Schema-aware checks use the fixture connection.
"""

from __future__ import annotations

import pytest


def _auth(signer):
    token = signer.sign(sub="user-abc")
    return {"Authorization": f"Bearer {token}"}


def _create_connection(client, signer, sample_connection) -> str:
    resp = client.post("/connections/test", json=sample_connection, headers=_auth(signer))
    assert resp.status_code == 200
    return resp.json()["connection"]["connection_id"]


def test_validate_requires_auth(client):
    resp = client.post("/api/validate", json={"sql": "SELECT 1"})
    assert resp.status_code == 401


def test_optimize_requires_auth(client):
    resp = client.post("/api/optimize", json={"sql": "SELECT 1"})
    assert resp.status_code == 401


def test_validate_syntax_only(client, signer):
    resp = client.post(
        "/api/validate",
        json={"sql": "SELECT id FROM users", "dialect": "postgres"},
        headers=_auth(signer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_valid"] is True
    assert body["parsed_statements"] == 1


def test_validate_malformed_syntax(client, signer):
    resp = client.post(
        "/api/validate",
        json={"sql": "SELECT * FORM users"},
        headers=_auth(signer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_valid"] is False
    assert body["syntax_errors"]


def test_validate_with_connection_flags_unknown_table(client, signer, sample_connection):
    connection_id = _create_connection(client, signer, sample_connection)
    resp = client.post(
        "/api/validate",
        json={"sql": "SELECT id FROM customers", "connection_id": connection_id},
        headers=_auth(signer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_valid"] is False
    assert any("customers" in e for e in body["schema_errors"])


def test_validate_unknown_connection_404(client, signer):
    resp = client.post(
        "/api/validate",
        json={"sql": "SELECT 1", "connection_id": "does-not-exist"},
        headers=_auth(signer),
    )
    assert resp.status_code == 404


def test_optimize_returns_rule_based_results(client, signer, sample_connection):
    connection_id = _create_connection(client, signer, sample_connection)
    resp = client.post(
        "/api/optimize",
        json={"sql": "SELECT * FROM orders", "connection_id": connection_id},
        headers=_auth(signer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["original_sql"] == "SELECT * FROM orders"
    rules = {o["rule"] for o in body["optimizations"]}
    assert "select-star" in rules
    assert body["rewritten_sql"] is not None
    # Rule-based only: no AI suggestion yet (FEAT-003 fills this in).
    assert body["suggested_sql"] is None
    assert body["provider"] is None
    assert "estimate" in body["performance_note"].lower()


def test_optimize_use_ai_still_rule_based_for_now(client, signer):
    resp = client.post(
        "/api/optimize",
        json={"sql": "SELECT * FROM orders", "use_ai": True},
        headers=_auth(signer),
    )
    assert resp.status_code == 200
    body = resp.json()
    # AI layer is not implemented until FEAT-003; endpoint defaults to rules.
    assert body["suggested_sql"] is None
    assert body["is_suggestion_valid"] is None


@pytest.mark.parametrize("dialect", ["postgres", "mysql"])
def test_validate_multi_dialect(client, signer, dialect):
    resp = client.post(
        "/api/validate",
        json={"sql": "SELECT id FROM users LIMIT 5", "dialect": dialect},
        headers=_auth(signer),
    )
    assert resp.status_code == 200
    assert resp.json()["is_valid"] is True
