"""Route-level tests for GET /api/connections/{connection_id}/schema.

Confirms the schema-detail endpoint is wired behind ``get_current_user``,
returns the normalized catalog metadata for the fixture connection (tables and
columns), isolates connections per user (unknown ids yield 404), and never
leaks a password anywhere in the response payload.
"""

from __future__ import annotations


def _auth(signer):
    token = signer.sign(sub="user-abc")
    return {"Authorization": f"Bearer {token}"}


def _create_connection(client, signer, sample_connection) -> str:
    resp = client.post("/api/connections/test", json=sample_connection, headers=_auth(signer))
    assert resp.status_code == 200
    return resp.json()["connection"]["connection_id"]


def test_schema_requires_auth(client):
    resp = client.get("/api/connections/some-id/schema")
    assert resp.status_code == 401


def test_schema_unknown_connection_404(client, signer):
    resp = client.get("/api/connections/does-not-exist/schema", headers=_auth(signer))
    assert resp.status_code == 404


def test_schema_returns_tables_and_columns(client, signer, sample_connection):
    connection_id = _create_connection(client, signer, sample_connection)
    resp = client.get(f"/api/connections/{connection_id}/schema", headers=_auth(signer))
    assert resp.status_code == 200
    body = resp.json()

    assert body["dialect"] == "postgres"
    tables = {t["name"]: t for t in body["tables"]}
    assert set(tables) == {"users", "orders"}

    users_cols = {c["name"]: c for c in tables["users"]["columns"]}
    assert set(users_cols) == {"id", "email", "created_at"}
    assert users_cols["id"]["is_primary_key"] is True
    assert users_cols["id"]["data_type"] == "integer"
    assert users_cols["email"]["nullable"] is False

    orders_cols = {c["name"] for c in tables["orders"]["columns"]}
    assert orders_cols == {"id", "user_id", "total", "status"}


def test_schema_response_has_no_password(client, signer, sample_connection):
    connection_id = _create_connection(client, signer, sample_connection)
    resp = client.get(f"/api/connections/{connection_id}/schema", headers=_auth(signer))
    assert resp.status_code == 200
    assert "password" not in resp.text.lower()
    assert "super-secret-pw" not in resp.text
