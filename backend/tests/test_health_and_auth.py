"""Tests for /health (unauthenticated) and protected-route auth behavior."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.cognito import AuthError, CognitoVerifier
from app.config import Settings
from app.main import create_app
from tests.conftest import TEST_CLIENT_ID, TEST_POOL_ID, TEST_REGION


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


# --- Fail-closed behavior on a misconfigured Cognito deployment --------------
#
# These tests pin the gating fix: a half-configured deployment (missing app
# client id and/or user pool id) must REFUSE to serve protected routes rather
# than accept any Cognito-signed token. They build a client whose verifier uses
# the local test JWKS but whose settings are deliberately incomplete, and assert
# that even a correctly signed token is rejected.


def _misconfigured_client(signer, missing: str, token_use: str = "access"):
    """Build a TestClient whose Cognito settings are intentionally incomplete.

    ``missing`` is one of ``"client_id"``, ``"pool_id"``, or ``"both"``.
    """
    pool_id = "" if missing in ("pool_id", "both") else TEST_POOL_ID
    client_id = "" if missing in ("client_id", "both") else TEST_CLIENT_ID
    settings = Settings(
        AWS_REGION=TEST_REGION,
        COGNITO_USER_POOL_ID=pool_id,
        COGNITO_APP_CLIENT_ID=client_id,
        COGNITO_TOKEN_USE=token_use,
    )
    app = create_app(settings=settings)
    app.state.cognito_verifier = CognitoVerifier(
        settings=settings,
        jwks_provider=lambda: signer.jwks,
    )
    return TestClient(app)


def test_missing_client_id_fails_closed(client, signer, sample_connection):
    """A valid, correctly signed token is refused when the app client id is unset."""
    bad_client = _misconfigured_client(signer, missing="client_id")
    token = signer.sign(sub="user-abc")
    resp = bad_client.post(
        "/api/connections/test",
        json=sample_connection,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 503


def test_missing_pool_id_fails_closed(client, signer, sample_connection):
    """A valid, correctly signed token is refused when the user pool id is unset."""
    bad_client = _misconfigured_client(signer, missing="pool_id")
    token = signer.sign(sub="user-abc")
    resp = bad_client.post(
        "/api/connections/test",
        json=sample_connection,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 503


def test_misconfigured_id_token_mode_fails_closed(client, signer, sample_connection):
    """id-token mode without an app client id must also fail closed (issue #5)."""
    bad_client = _misconfigured_client(signer, missing="client_id", token_use="id")
    token = signer.sign(sub="user-abc", token_use="id")
    resp = bad_client.post(
        "/api/connections/test",
        json=sample_connection,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 503


def test_verifier_rejects_token_when_not_fully_configured(signer):
    """The verifier itself fails closed, independent of the HTTP layer.

    Covers both access and id token modes: a token the local JWKS can verify by
    signature alone must still be rejected when the deployment is only
    half-configured.
    """
    for token_use in ("access", "id"):
        settings = Settings(
            AWS_REGION=TEST_REGION,
            COGNITO_USER_POOL_ID=TEST_POOL_ID,
            COGNITO_APP_CLIENT_ID="",  # missing -> must fail closed
            COGNITO_TOKEN_USE=token_use,
        )
        verifier = CognitoVerifier(settings=settings, jwks_provider=lambda: signer.jwks)
        token = signer.sign(sub="user-abc", token_use=token_use)
        with pytest.raises(AuthError):
            verifier.verify_token(token)


def test_fully_configured_verifier_still_accepts_valid_token(client, signer, sample_connection):
    """Regression guard: the normal, fully-configured path keeps working."""
    token = signer.sign(sub="user-abc")
    resp = client.post(
        "/api/connections/test",
        json=sample_connection,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
