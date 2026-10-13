"""Adapter factory mapping a dialect name to a DBAdapter implementation."""

from __future__ import annotations

from app.db.base import DBAdapter
from app.db.postgres import PostgresAdapter
from app.models.api_models import ConnectionConfig

# Dialects recognized by the platform. Only postgres is implemented in the MVP;
# the rest are explicit placeholders so the interface is ready to extend.
_SUPPORTED_DIALECTS = {"postgres", "postgresql", "mysql", "sqlserver", "sqlite", "oracle"}


def create_adapter(config: ConnectionConfig) -> DBAdapter:
    """Return the adapter for ``config.dialect`` or raise NotImplementedError."""
    dialect = config.dialect.strip().lower()
    if dialect in ("postgres", "postgresql"):
        return PostgresAdapter(config)
    if dialect in ("mysql", "sqlserver", "sqlite", "oracle"):
        raise NotImplementedError(f"Adapter for dialect '{dialect}' is not implemented yet")
    raise ValueError(f"Unknown dialect '{config.dialect}'")


def supported_dialects() -> set[str]:
    """Return the set of dialect names the platform recognizes."""
    return set(_SUPPORTED_DIALECTS)
