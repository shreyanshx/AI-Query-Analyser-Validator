"""Tests for /health (unauthenticated) and protected-route auth behavior."""

from __future__ import annotations


def test_health_is_public(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_protected_route_without_token_is_401(client, sample_connection):
    resp = client.post("/api/connections/test", json=sample_connection)
    assert resp.status_code == 401


def test_protected_route_with_invalid_token_is_401(client, sample_connection):
    resp = client.post(
        "/api/connections/test",
        json=sample_connection,
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


def test_protected_route_with_valid_token_is_200(client, signer, sample_connection):
    token = signer.sign(sub="user-abc")
    resp = client.post(
        "/api/connections/test",
        json=sample_connection,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["table_count"] == 2
    # Password must never be echoed back in the response.
    assert "password" not in resp.text.lower() or "super-secret-pw" not in resp.text


def test_expired_token_is_401(client, signer, sample_connection):
    token = signer.sign(sub="user-abc", expires_in=-10)
    resp = client.post(
        "/api/connections/test",
        json=sample_connection,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401
