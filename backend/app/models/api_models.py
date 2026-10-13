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


class Optimization(BaseModel):
    """A single rule-based optimization finding.

    ``rewritten_sql`` is populated only when a rule can propose a concrete
    rewrite. Performance implications are always estimates (see
    ``performance_note`` on the response).
    """

    rule: str
    severity: str = "info"
    message: str
    rewritten_sql: str | None = None


class OptimizeRequest(BaseModel):
    """Request to produce an optimization suggestion for SQL."""

    sql: str
    dialect: str = "postgres"
    connection_id: str | None = None
    use_ai: bool = False


class OptimizeResponse(BaseModel):
    """Normalized optimization suggestion result.

    The rule-based engine always populates ``optimizations`` and
    ``rewritten_sql``. The AI layer (added in FEAT-003) may additionally set
    ``suggested_sql`` / ``explanation`` / ``provider`` and revalidate its
    suggestion with the deterministic validator (``is_suggestion_valid``).
    """

    original_sql: str
    rewritten_sql: str | None = None
    optimizations: list[Optimization] = Field(default_factory=list)
    performance_note: str = (
        "Performance impact is an estimate from static analysis; it is not based "
        "on query execution or EXPLAIN plans."
    )
    # AI-related fields; left unset by the rule-based engine.
    suggested_sql: str | None = None
    explanation: str | None = None
    provider: str | None = None
    is_suggestion_valid: bool | None = None
