"""Abstract database adapter interface.

Adapters are used ONLY for connection checks, read-only schema introspection,
and opt-in data sampling. They must never execute user-entered or AI-generated
SQL. All catalog queries are read-only and parameterized.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.models.api_models import ConnectionConfig
from app.models.schema_models import NormalizedSchema


class DBAdapter(ABC):
    """Interface every database adapter must implement."""

    def __init__(self, config: ConnectionConfig) -> None:
        self.config = config

    @abstractmethod
    def test_connection(self) -> bool:
        """Return True if a connection can be established, else raise/return False."""

    @abstractmethod
    def introspect_schema(self) -> NormalizedSchema:
        """Introspect catalog metadata and return a NormalizedSchema."""

    @abstractmethod
    def sample_column(self, table: str, column: str, limit: int = 20) -> list[Any]:
        """Return up to ``limit`` sample values for opt-in data sampling."""
