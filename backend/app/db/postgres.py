"""PostgreSQL adapter.

Uses psycopg with read-only, parameterized ``information_schema`` and
``pg_catalog`` queries. It never executes user-entered or AI-generated SQL.
"""

from __future__ import annotations

from typing import Any

from app.db.base import DBAdapter
from app.logging_utils import get_logger
from app.models.api_models import ConnectionConfig
from app.models.schema_models import (
    Column,
    ForeignKey,
    Index,
    NormalizedSchema,
    Table,
)

logger = get_logger(__name__)


class PostgresAdapter(DBAdapter):
    """Read-only PostgreSQL schema introspection adapter."""

    def __init__(self, config: ConnectionConfig) -> None:
        super().__init__(config)

    def _connect(self) -> Any:
        import psycopg

        return psycopg.connect(
            host=self.config.host,
            port=self.config.port,
            dbname=self.config.database,
            user=self.config.username,
            password=self.config.password.get_secret_value(),
            sslmode="require" if self.config.ssl else "prefer",
            connect_timeout=10,
            autocommit=True,
        )

    def test_connection(self) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True

    def introspect_schema(self) -> NormalizedSchema:
        with self._connect() as conn:
            with conn.cursor() as cur:
                tables = self._load_tables(cur)
                self._load_columns(cur, tables)
                self._load_primary_keys(cur, tables)
                self._load_indexes(cur, tables)
                self._load_foreign_keys(cur, tables)
        return NormalizedSchema(
            dialect="postgres",
            database=self.config.database,
            tables=list(tables.values()),
        )

    def sample_column(self, table: str, column: str, limit: int = 20) -> list[Any]:
        # Identifiers are validated against the live catalog before use so that
        # only existing, known-safe identifiers reach a (quoted) query.
        import psycopg
        from psycopg import sql as pgsql

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = %s
                      AND column_name = %s
                    """,
                    (table, column),
                )
                if cur.fetchone() is None:
                    raise ValueError("Unknown table or column for sampling")

                query = pgsql.SQL("SELECT {col} FROM {tbl} LIMIT %s").format(
                    col=pgsql.Identifier(column),
                    tbl=pgsql.Identifier("public", table),
                )
                cur.execute(query, (int(limit),))
                try:
                    return [row[0] for row in cur.fetchall()]
                except psycopg.ProgrammingError:
                    return []

    # --- internal helpers -------------------------------------------------

    @staticmethod
    def _load_tables(cur: Any) -> dict[str, Table]:
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY table_name
            """)
        return {row[0]: Table(name=row[0], schema_name="public") for row in cur.fetchall()}

    @staticmethod
    def _load_columns(cur: Any, tables: dict[str, Table]) -> None:
        cur.execute("""
            SELECT table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
            """)
        for table_name, column_name, data_type, is_nullable, default in cur.fetchall():
            table = tables.get(table_name)
            if table is None:
                continue
            table.columns.append(
                Column(
                    name=column_name,
                    data_type=data_type,
                    nullable=(is_nullable == "YES"),
                    default=default,
                )
            )

    @staticmethod
    def _load_primary_keys(cur: Any, tables: dict[str, Table]) -> None:
        cur.execute("""
            SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = 'public'
            """)
        pk_map: dict[str, set[str]] = {}
        for table_name, column_name in cur.fetchall():
            pk_map.setdefault(table_name, set()).add(column_name)
        for table_name, pk_columns in pk_map.items():
            table = tables.get(table_name)
            if table is None:
                continue
            for column in table.columns:
                if column.name in pk_columns:
                    column.is_primary_key = True

    @staticmethod
    def _load_indexes(cur: Any, tables: dict[str, Table]) -> None:
        cur.execute("""
            SELECT t.relname AS table_name,
                   i.relname AS index_name,
                   ix.indisunique AS is_unique,
                   a.attname AS column_name
            FROM pg_class t
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_index ix ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
            WHERE n.nspname = 'public' AND t.relkind = 'r'
            ORDER BY t.relname, i.relname
            """)
        index_map: dict[tuple[str, str], Index] = {}
        for table_name, index_name, is_unique, column_name in cur.fetchall():
            key = (table_name, index_name)
            if key not in index_map:
                index_map[key] = Index(name=index_name, unique=bool(is_unique))
            index_map[key].columns.append(column_name)
        for (table_name, _), index in index_map.items():
            table = tables.get(table_name)
            if table is not None:
                table.indexes.append(index)

    @staticmethod
    def _load_foreign_keys(cur: Any, tables: dict[str, Table]) -> None:
        cur.execute("""
            SELECT tc.table_name,
                   tc.constraint_name,
                   kcu.column_name,
                   ccu.table_name AS referenced_table,
                   ccu.column_name AS referenced_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
            """)
        fk_map: dict[tuple[str, str], ForeignKey] = {}
        for table_name, constraint_name, column, ref_table, ref_column in cur.fetchall():
            key = (table_name, constraint_name)
            if key not in fk_map:
                fk_map[key] = ForeignKey(name=constraint_name, referenced_table=ref_table)
            fk_map[key].columns.append(column)
            fk_map[key].referenced_columns.append(ref_column)
        for (table_name, _), fk in fk_map.items():
            table = tables.get(table_name)
            if table is not None:
                table.foreign_keys.append(fk)
