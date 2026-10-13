"""Schema introspection service with an in-memory TTL cache.

Normalized schemas are cached per (cognito_sub, connection fingerprint) so that
data remains isolated by authenticated user. Optional data sampling is gated by
``settings.ENABLE_DATA_SAMPLING`` plus a per-request opt-in flag, and sensitive
columns are always excluded.
"""

from __future__ import annotations

from typing import Any

from cachetools import TTLCache

from app.config import Settings, get_settings
from app.db.base import DBAdapter
from app.db.factory import create_adapter
from app.logging_utils import get_logger
from app.models.api_models import ConnectionConfig
from app.models.schema_models import NormalizedSchema

logger = get_logger(__name__)


class SchemaService:
    """Introspects, normalizes, and caches database schema metadata."""

    def __init__(
        self,
        settings: Settings | None = None,
        adapter_factory: Any = create_adapter,
    ) -> None:
        self._settings = settings or get_settings()
        self._adapter_factory = adapter_factory
        self._cache: TTLCache[str, NormalizedSchema] = TTLCache(
            maxsize=256, ttl=self._settings.SCHEMA_CACHE_TTL_SECONDS
        )

    @staticmethod
    def _cache_key(cognito_sub: str, config: ConnectionConfig) -> str:
        return f"{cognito_sub}::{config.fingerprint()}"

    def get_schema(
        self,
        cognito_sub: str,
        config: ConnectionConfig,
        force_refresh: bool = False,
    ) -> NormalizedSchema:
        """Return the normalized schema, using the cache unless forced."""
        key = self._cache_key(cognito_sub, config)
        if not force_refresh:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
        adapter: DBAdapter = self._adapter_factory(config)
        schema = adapter.introspect_schema()
        self._cache[key] = schema
        return schema

    def invalidate(self, cognito_sub: str, config: ConnectionConfig) -> None:
        """Drop any cached schema for the given user + connection."""
        self._cache.pop(self._cache_key(cognito_sub, config), None)

    def sample_column(
        self,
        config: ConnectionConfig,
        table: str,
        column: str,
        opt_in: bool,
        limit: int = 20,
    ) -> list[Any]:
        """Return sample values only when sampling is globally and locally enabled.

        Sensitive columns (by name) are never sampled.
        """
        if not self._settings.ENABLE_DATA_SAMPLING:
            raise PermissionError("Data sampling is disabled by configuration")
        if not opt_in:
            raise PermissionError("Data sampling requires per-request opt-in")
        if column.lower() in {c.lower() for c in self._settings.SENSITIVE_COLUMN_NAMES}:
            raise PermissionError(f"Column '{column}' is excluded from sampling")

        adapter: DBAdapter = self._adapter_factory(config)
        return adapter.sample_column(table, column, limit=limit)
