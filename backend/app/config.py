"""Application configuration via pydantic-settings.

Settings are read from environment variables and an optional ``.env`` file.
When ``SECRETS_MANAGER_SECRET_ID`` is set, secrets are lazily and best-effort
loaded from AWS Secrets Manager and merged into the environment before
settings are constructed; env values that are already present win over
Secrets Manager values so local overrides remain possible.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def load_secrets_from_secrets_manager() -> None:
    """Best-effort load secrets from AWS Secrets Manager into os.environ.

    This is intentionally lazy and tolerant: if boto3 is unavailable, the
    secret id is unset, or the call fails, we simply fall back to the existing
    environment. Existing environment variables are never overwritten so that
    local configuration always takes precedence.
    """
    secret_id = os.environ.get("SECRETS_MANAGER_SECRET_ID")
    if not secret_id:
        return

    region = os.environ.get("AWS_REGION", "us-east-1")
    try:
        import boto3  # imported lazily; optional at runtime

        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_id)
        raw = response.get("SecretString")
        if not raw:
            return
        data = json.loads(raw)
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            # Do not overwrite values explicitly provided in the environment.
            if key not in os.environ and value is not None:
                os.environ[key] = str(value)
    except Exception:  # noqa: BLE001 - best effort, never fatal
        logger.warning(
            "Could not load secrets from Secrets Manager; falling back to environment.",
            exc_info=False,
        )


class Settings(BaseSettings):
    """Runtime configuration for the backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # AWS / Cognito
    AWS_REGION: str = "us-east-1"
    COGNITO_USER_POOL_ID: str = ""
    COGNITO_APP_CLIENT_ID: str = ""
    # Which token_use value to require: "access" (default) or "id".
    COGNITO_TOKEN_USE: str = "access"

    # AI provider configuration
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    BEDROCK_REGION: str = ""
    BEDROCK_MODEL_ID: str = ""
    AI_PROVIDER_ORDER: str = "gemini,bedrock,openai,anthropic"

    # Schema caching
    SCHEMA_CACHE_TTL_SECONDS: int = 300

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173"

    # Feature flags
    ENABLE_DATA_SAMPLING: bool = False
    EXPLAIN_ENABLED: bool = False

    # Secrets
    SECRETS_MANAGER_SECRET_ID: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def COGNITO_ISSUER(self) -> str:
        """Derived Cognito issuer URL used for JWKS and token validation."""
        if not self.COGNITO_USER_POOL_ID:
            return ""
        return (
            f"https://cognito-idp.{self.AWS_REGION}.amazonaws.com/" f"{self.COGNITO_USER_POOL_ID}"
        )

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS origins as a list, split on commas and whitespace-trimmed."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def ai_provider_order_list(self) -> list[str]:
        """Configured AI provider fallback chain as an ordered list."""
        return [p.strip() for p in self.AI_PROVIDER_ORDER.split(",") if p.strip()]

    # Sensitive column names excluded from any opt-in data sampling.
    SENSITIVE_COLUMN_NAMES: list[str] = Field(
        default_factory=lambda: [
            "password",
            "passwd",
            "pwd",
            "secret",
            "token",
            "api_key",
            "apikey",
            "ssn",
            "credit_card",
            "card_number",
        ]
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance, loading Secrets Manager first."""
    load_secrets_from_secrets_manager()
    return Settings()
