"""Unit tests for the rule-based optimizer.

All tests use the fixture NormalizedSchema only; no live DB and no SQL
execution.
"""

from __future__ import annotations

import pytest

from app.models.api_models import Optimization
from app.services.optimizer import RuleBasedOptimizer


@pytest.fixture
def schema(fixture_schema):
    return fixture_schema


@pytest.fixture
def optimizer() -> RuleBasedOptimizer:
    return RuleBasedOptimizer()


def _rules(findings: list[Optimization]) -> set[str]:
    return {f.rule for f in findings}


def _find(findings: list[Optimization], rule: str) -> Optimization | None:
    return next((f for f in findings if f.rule == rule), None)


def test_select_star_expands_columns(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("SELECT * FROM orders", schema=schema)
    star = _find(findings, "select-star")
    assert star is not None
    assert star.rewritten_sql is not None
    # Rewrite should list the explicit orders columns, not a star.
    assert "*" not in star.rewritten_sql
    for col in ("id", "user_id", "total", "status"):
        assert col in star.rewritten_sql


def test_update_without_where_is_flagged(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("UPDATE orders SET status = 'x'", schema=schema)
    missing = _find(findings, "missing-where")
    assert missing is not None
    assert missing.severity == "error"


def test_update_with_where_not_flagged(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("UPDATE orders SET status = 'x' WHERE id = 1", schema=schema)
    assert "missing-where" not in _rules(findings)


def test_delete_without_where_is_flagged(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("DELETE FROM orders", schema=schema)
    assert "missing-where" in _rules(findings)


def test_where_on_non_indexed_column_suggests_index(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("SELECT id FROM orders WHERE status = 'x'", schema=schema)
    suggestion = _find(findings, "index-suggestion")
    assert suggestion is not None
    assert "status" in suggestion.message


def test_where_on_indexed_pk_column_no_index_suggestion(
    optimizer: RuleBasedOptimizer, schema
) -> None:
    findings = optimizer.optimize("SELECT email FROM users WHERE id = 1", schema=schema)
    assert "index-suggestion" not in _rules(findings)


def test_leading_wildcard_like_is_non_sargable(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("SELECT id FROM users WHERE email LIKE '%foo'", schema=schema)
    assert "non-sargable-like" in _rules(findings)


def test_trailing_wildcard_like_not_flagged(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("SELECT id FROM users WHERE email LIKE 'foo%'", schema=schema)
    assert "non-sargable-like" not in _rules(findings)


def test_function_wrapped_filter_is_non_sargable(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("SELECT id FROM users WHERE LOWER(email) = 'x'", schema=schema)
    assert "non-sargable-function" in _rules(findings)


def test_missing_join_condition_detected(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("SELECT u.id FROM users u JOIN orders o", schema=schema)
    assert "missing-join-condition" in _rules(findings)


def test_explicit_cross_join_not_flagged(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("SELECT u.id FROM users u CROSS JOIN orders o", schema=schema)
    assert "missing-join-condition" not in _rules(findings)


def test_join_with_on_not_flagged(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize(
        "SELECT u.id FROM users u JOIN orders o ON u.id = o.user_id", schema=schema
    )
    assert "missing-join-condition" not in _rules(findings)


def test_unbounded_select_suggests_limit(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("SELECT id FROM users", schema=schema)
    assert "unbounded-select" in _rules(findings)


def test_select_with_limit_not_flagged(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("SELECT id FROM users LIMIT 10", schema=schema)
    assert "unbounded-select" not in _rules(findings)


def test_aggregate_without_group_not_flagged(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("SELECT COUNT(*) FROM users", schema=schema)
    assert "unbounded-select" not in _rules(findings)


def test_malformed_sql_returns_no_findings(optimizer: RuleBasedOptimizer, schema) -> None:
    # The optimizer leaves syntax reporting to the validator; it just no-ops.
    assert optimizer.optimize("SELECT * FORM orders", schema=schema) == []


def test_rewritten_sql_helper(optimizer: RuleBasedOptimizer, schema) -> None:
    findings = optimizer.optimize("SELECT * FROM orders", schema=schema)
    assert optimizer.rewritten_sql(findings) is not None


def test_findings_without_schema(optimizer: RuleBasedOptimizer) -> None:
    # Without a schema, structural rules still fire but index suggestions do not.
    findings = optimizer.optimize("SELECT * FROM orders WHERE status = 'x'")
    assert "select-star" in _rules(findings)
    assert "index-suggestion" not in _rules(findings)
