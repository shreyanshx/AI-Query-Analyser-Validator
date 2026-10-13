"""Shared test fixtures.

These fixtures let auth and DB behavior be exercised without any live Cognito
or SQL database:

* ``signer`` generates a local RSA keypair, exposes the JWKS, and signs fake
  Cognito access tokens.
* The ``CognitoVerifier`` is injected with the local JWKS so signature
  verification succeeds against the test keypair.
* ``fake_adapter`` returns a small fixed NormalizedSchema.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jose import jwk, jwt

from app.auth.cognito import CognitoVerifier
from app.config import Settings
from app.db.base import DBAdapter
from app.main import create_app
from app.models.api_models import ConnectionConfig
from app.models.schema_models import Column, NormalizedSchema, Table

TEST_REGION = "us-east-1"
TEST_POOL_ID = "us-east-1_testpool"
TEST_CLIENT_ID = "test-app-client-id"
TEST_ISSUER = f"https://cognito-idp.{TEST_REGION}.amazonaws.com/{TEST_POOL_ID}"
TEST_KID = "test-key-1"


@dataclass
class Signer:
    """Holds the test RSA key and can sign fake Cognito tokens."""

    private_pem: str
    jwks: dict[str, Any]

    def sign(
        self,
        sub: str = "user-123",
        token_use: str = "access",
        client_id: str = TEST_CLIENT_ID,
        expires_in: int = 3600,
        issuer: str = TEST_ISSUER,
    ) -> str:
        now = int(time.time())
        claims = {
            "sub": sub,
            "token_use": token_use,
            "client_id": client_id,
            "iss": issuer,
            "iat": now,
            "exp": now + expires_in,
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(claims, self.private_pem, algorithm="RS256", headers={"kid": TEST_KID})


@pytest.fixture(scope="session")
def signer() -> Signer:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    from cryptography.hazmat.primitives import serialization

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )

    public_jwk = jwk.construct(public_pem, "RS256").to_dict()
    public_jwk.update({"kid": TEST_KID, "use": "sig", "alg": "RS256"})
    jwks = {"keys": [public_jwk]}
    return Signer(private_pem=private_pem, jwks=jwks)


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        AWS_REGION=TEST_REGION,
        COGNITO_USER_POOL_ID=TEST_POOL_ID,
        COGNITO_APP_CLIENT_ID=TEST_CLIENT_ID,
        COGNITO_TOKEN_USE="access",
    )


class FakeAdapter(DBAdapter):
    """In-memory adapter returning a fixed NormalizedSchema."""

    def test_connection(self) -> bool:
        return True

    def introspect_schema(self) -> NormalizedSchema:
        return NormalizedSchema(
            dialect="postgres",
            database="testdb",
            tables=[
                Table(
                    name="users",
                    schema_name="public",
                    columns=[
                        Column(name="id", data_type="integer", nullable=False, is_primary_key=True),
                        Column(name="email", data_type="text", nullable=False),
                        Column(name="created_at", data_type="timestamp", nullable=False),
                    ],
                ),
                Table(
                    name="orders",
                    schema_name="public",
                    columns=[
                        Column(name="id", data_type="integer", nullable=False, is_primary_key=True),
                        Column(name="user_id", data_type="integer", nullable=False),
                        Column(name="total", data_type="numeric", nullable=True),
                        Column(name="status", data_type="text", nullable=True),
                    ],
                ),
            ],
        )

    def sample_column(self, table: str, column: str, limit: int = 20) -> list[Any]:
        return []


@pytest.fixture
def fake_adapter() -> type[FakeAdapter]:
    return FakeAdapter


@pytest.fixture
def fixture_schema() -> NormalizedSchema:
    """The fixture NormalizedSchema used by validator/optimizer unit tests."""
    config = ConnectionConfig(
        dialect="postgres",
        host="db.example.com",
        port=5432,
        database="testdb",
        username="reader",
        password="super-secret-pw",
    )
    return FakeAdapter(config).introspect_schema()


@pytest.fixture
def app(signer: Signer, test_settings: Settings, fake_adapter: type[FakeAdapter]):
    from app.services.schema import SchemaService

    application = create_app(settings=test_settings)
    application.state.cognito_verifier = CognitoVerifier(
        settings=test_settings,
        jwks_provider=lambda: signer.jwks,
    )
    application.state.schema_service = SchemaService(
        settings=test_settings,
        adapter_factory=lambda config: fake_adapter(config),
    )
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def sample_connection() -> dict[str, Any]:
    config = ConnectionConfig(
        dialect="postgres",
        host="db.example.com",
        port=5432,
        database="testdb",
        username="reader",
        password="super-secret-pw",
    )
    return config.model_dump(mode="json") | {"password": "super-secret-pw"}
