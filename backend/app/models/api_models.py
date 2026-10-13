"""API request and response models.

Database passwords use ``SecretStr`` so they are never serialized back to
clients or logged by accident.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr


class ConnectionConfig(BaseModel):
    """Database connection parameters supplied by an authenticated user."""

    dialect: str = "postgres"
    host: str
    port: int = 5432
    database: str
    username: str
    password: SecretStr
    ssl: bool = False

    def fingerprint(self) -> str:
        """Stable, non-secret identifier for cache keying."""
        return f"{self.dialect}://{self.username}@{self.host}:{self.port}/{self.database}"


class ConnectionInfo(BaseModel):
    """Connection metadata safe to return to clients (no password)."""

    connection_id: str
    dialect: str
    host: str
    port: int
    database: str
    username: str


class TestConnectionResponse(BaseModel):
    """Result of testing a connection and introspecting its schema."""

    connection: ConnectionInfo
    ok: bool
    table_count: int


class ValidateRequest(BaseModel):
    """Request to validate one or more SQL statements."""

    sql: str
    dialect: str = "postgres"
    connection_id: str | None = None


class ValidationResult(BaseModel):
    """Deterministic validation result for submitted SQL."""

    syntax_errors: list[str] = Field(default_factory=list)
    schema_errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    parsed_statements: int = 0
    is_valid: bool = False


class OptimizeRequest(BaseModel):
    """Request to produce an AI optimization suggestion for SQL."""

    sql: str
    dialect: str = "postgres"
    connection_id: str | None = None


class OptimizeResponse(BaseModel):
    """Normalized AI optimization suggestion result."""

    original_sql: str
    suggested_sql: str
    explanation: str
    optimizations: list[str] = Field(default_factory=list)
    provider: str
    is_suggestion_valid: bool
    performance_note: str
