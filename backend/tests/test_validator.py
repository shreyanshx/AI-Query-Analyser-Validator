"""Unit tests for the deterministic SQL validator.

All tests run purely over the fixture NormalizedSchema; there is no live DB and
no SQL execution path.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import sqlglot

from app.services.validator import SqlValidator, normalize_dialect


@pytest.fixture
def schema(fixture_schema):
    return fixture_schema


@pytest.fixture
def validator() -> SqlValidator:
    return SqlValidator()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, email FROM users",
        "INSERT INTO users (id, email, created_at) VALUES (1, 'a@b.c', NOW())",
        "UPDATE orders SET status = 'done' WHERE id = 1",
        "DELETE FROM orders WHERE id = 1",
        "CREATE TABLE widgets (id integer PRIMARY KEY, name text)",
        "WITH recent AS (SELECT id FROM users) SELECT r.id FROM recent r",
        "BEGIN; SELECT 1; COMMIT;",
    ],
)
def test_valid_statements_parse(validator: SqlValidator, sql: str) -> None:
    result = validator.validate_syntax(sql, dialect="postgres")
    assert result.is_valid
    assert result.syntax_errors == []
    assert result.statements


def test_statement_types_are_classified(validator: SqlValidator) -> None:
    result = validator.validate_syntax(
        "SELECT 1; UPDATE orders SET status = 'x' WHERE id = 1;",
        dialect="postgres",
    )
    types = [s.statement_type for s in result.statements]
    assert types == ["SELECT", "UPDATE"]


def test_malformed_sql_reports_syntax_errors(validator: SqlValidator) -> None:
    result = validator.validate("SELECT * FORM users", dialect="postgres")
    assert not result.is_valid
    assert result.syntax_errors
    assert any("line" in err.lower() for err in result.syntax_errors)
    # Schema validation must be skipped when syntax is invalid.
    assert result.schema_errors == []


def test_empty_sql_is_invalid(validator: SqlValidator) -> None:
    result = validator.validate("   ", dialect="postgres")
    assert not result.is_valid
    assert result.syntax_errors


def test_unknown_table_is_flagged(validator: SqlValidator, schema) -> None:
    result = validator.validate("SELECT id FROM customers", schema=schema)
    assert not result.is_valid
    assert any("customers" in err for err in result.schema_errors)


def test_unknown_column_is_flagged(validator: SqlValidator, schema) -> None:
    result = validator.validate("SELECT nope FROM users", schema=schema)
    assert not result.is_valid
    assert any("nope" in err for err in result.schema_errors)


def test_unknown_qualified_column_is_flagged(validator: SqlValidator, schema) -> None:
    result = validator.validate("SELECT u.missing FROM users u", schema=schema)
    assert not result.is_valid
    assert any("missing" in err for err in result.schema_errors)


def test_cte_name_is_not_unknown_table(validator: SqlValidator, schema) -> None:
    sql = "WITH recent AS (SELECT id FROM users) SELECT r.id FROM recent r"
    result = validator.validate(sql, schema=schema)
    assert result.is_valid, result
    assert result.schema_errors == []


def test_table_alias_is_not_unknown_table(validator: SqlValidator, schema) -> None:
    result = validator.validate("SELECT u.email FROM users u", schema=schema)
    assert result.is_valid, result
    assert result.schema_errors == []


def test_valid_join_against_schema(validator: SqlValidator, schema) -> None:
    sql = "SELECT u.email, o.total FROM users u JOIN orders o ON u.id = o.user_id"
    result = validator.validate(sql, schema=schema)
    assert result.is_valid, result
    assert result.schema_errors == []


def test_unqualified_column_in_multi_table_warns(validator: SqlValidator, schema) -> None:
    sql = "SELECT total FROM users u JOIN orders o ON u.id = o.user_id"
    result = validator.validate(sql, schema=schema)
    assert result.is_valid
    assert any("without a table qualifier" in w for w in result.warnings)


def test_insert_column_list_against_schema_is_clean(validator: SqlValidator, schema) -> None:
    """INSERT column lists on a known table must not surface schema errors."""
    sql = "INSERT INTO users (id, email, created_at) VALUES (1, 'a@b.c', NOW())"
    result = validator.validate(sql, schema=schema)
    assert result.is_valid, result
    assert result.schema_errors == []


def test_insert_into_unknown_table_is_flagged(validator: SqlValidator, schema) -> None:
    """INSERT into a table that is not in the schema is still flagged."""
    result = validator.validate(
        "INSERT INTO customers (id) VALUES (1)",
        schema=schema,
    )
    assert not result.is_valid
    assert any("customers" in err for err in result.schema_errors)


def test_create_table_is_not_unknown_table(validator: SqlValidator, schema) -> None:
    """CREATE TABLE defines a new object; it must not be an 'Unknown table'.

    The columns declared in the definition are new and must not be compared
    against the base schema either (issue #6 regression guard).
    """
    result = validator.validate(
        "CREATE TABLE widgets (id integer PRIMARY KEY, name text)",
        schema=schema,
    )
    assert result.is_valid, result
    assert result.schema_errors == []
    assert result.warnings == []


def test_create_table_as_select_still_validates_source(validator: SqlValidator, schema) -> None:
    """CREATE TABLE ... AS SELECT: the new table is fine, but a bad source is caught."""
    good = validator.validate("CREATE TABLE t2 AS SELECT id FROM users", schema=schema)
    assert good.is_valid, good
    assert good.schema_errors == []

    bad = validator.validate("CREATE TABLE t3 AS SELECT id FROM customers", schema=schema)
    assert not bad.is_valid
    assert any("customers" in err for err in bad.schema_errors)


def test_create_index_target_table_is_validated(validator: SqlValidator, schema) -> None:
    """CREATE INDEX ... ON references an existing table, which is still checked."""
    good = validator.validate("CREATE INDEX idx_email ON users (email)", schema=schema)
    assert good.is_valid, good
    assert good.schema_errors == []

    bad = validator.validate("CREATE INDEX idx_x ON customers (email)", schema=schema)
    assert not bad.is_valid
    assert any("customers" in err for err in bad.schema_errors)


@pytest.mark.parametrize("dialect", ["postgres", "mysql"])
def test_multi_dialect_parse_smoke(validator: SqlValidator, dialect: str) -> None:
    result = validator.validate_syntax("SELECT id FROM users LIMIT 5", dialect=dialect)
    assert result.is_valid


def test_normalize_dialect_mapping() -> None:
    assert normalize_dialect("postgresql") == "postgres"
    assert normalize_dialect("sqlserver") == "tsql"
    assert normalize_dialect("MariaDB") == "mysql"
    assert normalize_dialect(None) == "postgres"
    assert normalize_dialect("unknown-dialect") == "postgres"


def test_validator_never_executes_sql(validator: SqlValidator, schema) -> None:
    """There must be no SQL execution path: parsing/analysis only.

    We assert the validator never touches a DB cursor/execute by ensuring no
    such attribute is invoked (the validator has no DB dependency at all).
    """
    with patch("app.services.validator.sqlglot.parse", wraps=sqlglot.parse) as parse_spy:
        validator.validate("SELECT id FROM users", schema=schema)
    assert parse_spy.called
    assert not hasattr(validator, "execute")
    assert not hasattr(validator, "cursor")
