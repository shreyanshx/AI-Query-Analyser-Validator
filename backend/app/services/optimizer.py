"""Rule-based SQL optimizer built on SQLGlot.

Like the validator, this module performs *static* analysis only. It inspects the
SQLGlot AST plus the cached normalized schema and NEVER executes SQL. Each rule
is a small pure function over ``(expression, schema)`` returning zero or more
:class:`Optimization` findings, which keeps every rule independently
unit-testable.

All performance implications are estimates: they come from structural analysis,
not from executing the query or reading an EXPLAIN plan.
"""

from __future__ import annotations

from collections.abc import Callable

import sqlglot
from sqlglot import exp

from app.models.api_models import Optimization
from app.models.schema_models import NormalizedSchema, Table
from app.services.validator import normalize_dialect

# A rule takes the parsed statement + schema and returns findings.
Rule = Callable[[exp.Expression, NormalizedSchema | None], list[Optimization]]


def _tables_in_scope(
    expression: exp.Expression, schema: NormalizedSchema | None
) -> dict[str, Table]:
    """Map alias (or table name) -> schema Table for real tables in the query."""
    if schema is None:
        return {}
    by_name = {t.name.lower(): t for t in schema.tables}
    scope: dict[str, Table] = {}
    for table in expression.find_all(exp.Table):
        real = by_name.get(table.name.lower())
        if real is None:
            continue
        alias = (table.alias or table.name).lower()
        scope[alias] = real
    return scope


def _indexed_columns(table: Table) -> set[str]:
    """Return the set of columns that are indexed (incl. primary keys)."""
    indexed: set[str] = set()
    for col in table.columns:
        if col.is_primary_key:
            indexed.add(col.name.lower())
    for index in table.indexes:
        for col in index.columns:
            indexed.add(col.lower())
    return indexed


def _resolve_column_table(column: exp.Column, scope: dict[str, Table]) -> Table | None:
    """Resolve the schema Table a column belongs to, if determinable."""
    qualifier = column.table.lower() if column.table else ""
    if qualifier:
        return scope.get(qualifier)
    # Unqualified: resolvable only when exactly one table owns the column.
    col_name = column.name.lower()
    owners = [tbl for tbl in scope.values() if any(c.name.lower() == col_name for c in tbl.columns)]
    if len(owners) == 1:
        return owners[0]
    return None


# -- Individual rules -----------------------------------------------------------


def rule_select_star(
    expression: exp.Expression, schema: NormalizedSchema | None
) -> list[Optimization]:
    """Flag ``SELECT *`` and, when the schema is known, propose explicit columns."""
    findings: list[Optimization] = []
    for select in expression.find_all(exp.Select):
        stars = [e for e in select.expressions if isinstance(e, exp.Star)]
        if not stars:
            continue
        scope = _tables_in_scope(select, schema)
        rewritten: str | None = None
        if len(scope) == 1:
            ((alias, table),) = scope.items()
            # Qualify columns when the table has an explicit alias.
            table_node = next(iter(select.find_all(exp.Table)), None)
            use_alias = bool(table_node and table_node.alias)
            prefix = f"{alias}." if use_alias else ""
            columns = ", ".join(f"{prefix}{c.name}" for c in table.columns)
            if columns:
                new_select = select.copy()
                new_select.set(
                    "expressions",
                    [exp.column(c.name, table=alias if use_alias else None) for c in table.columns],
                )
                rewritten = new_select.sql(dialect=None)
        findings.append(
            Optimization(
                rule="select-star",
                severity="warning",
                message=(
                    "Avoid SELECT *; list only the columns you need to reduce I/O "
                    "and avoid breaking on schema changes."
                ),
                rewritten_sql=rewritten,
            )
        )
    return findings


def rule_missing_where(
    expression: exp.Expression, schema: NormalizedSchema | None
) -> list[Optimization]:
    """Warn on UPDATE / DELETE statements that lack a WHERE clause."""
    findings: list[Optimization] = []
    for node in expression.find_all(exp.Update, exp.Delete):
        if node.args.get("where") is None:
            verb = type(node).__name__.upper()
            findings.append(
                Optimization(
                    rule="missing-where",
                    severity="error",
                    message=(
                        f"{verb} has no WHERE clause and will affect every row. "
                        "Add a WHERE clause unless this is intentional."
                    ),
                )
            )
    return findings


def rule_index_suggestions(
    expression: exp.Expression, schema: NormalizedSchema | None
) -> list[Optimization]:
    """Suggest indexes for filter/join/order columns that are not indexed."""
    if schema is None:
        return []
    findings: list[Optimization] = []
    seen: set[tuple[str, str]] = set()

    for select in expression.find_all(exp.Select):
        scope = _tables_in_scope(select, schema)
        if not scope:
            continue

        candidate_columns: list[exp.Column] = []
        where = select.args.get("where")
        if where is not None:
            candidate_columns.extend(where.find_all(exp.Column))
        for join in select.find_all(exp.Join):
            on = join.args.get("on")
            if on is not None:
                candidate_columns.extend(on.find_all(exp.Column))
        order = select.args.get("order")
        if order is not None:
            candidate_columns.extend(order.find_all(exp.Column))

        for column in candidate_columns:
            table = _resolve_column_table(column, scope)
            if table is None:
                continue
            col_name = column.name.lower()
            if not any(c.name.lower() == col_name for c in table.columns):
                continue
            if col_name in _indexed_columns(table):
                continue
            key = (table.name.lower(), col_name)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                Optimization(
                    rule="index-suggestion",
                    severity="info",
                    message=(
                        f"Column {table.name}.{column.name} is used in a filter, "
                        "join, or ORDER BY but is not indexed. An index may improve "
                        "performance (estimate)."
                    ),
                )
            )
    return findings


def rule_leading_wildcard_like(
    expression: exp.Expression, schema: NormalizedSchema | None
) -> list[Optimization]:
    """Flag ``LIKE '%x'`` leading-wildcard patterns as non-index-friendly."""
    findings: list[Optimization] = []
    for like in expression.find_all(exp.Like, exp.ILike):
        pattern = like.expression
        if isinstance(pattern, exp.Literal) and pattern.is_string:
            value = pattern.this or ""
            if value.startswith("%") or value.startswith("_"):
                findings.append(
                    Optimization(
                        rule="non-sargable-like",
                        severity="warning",
                        message=(
                            f"Leading-wildcard pattern {pattern.sql()} cannot use a "
                            "standard B-tree index. Consider a trigram/full-text "
                            "index or restructuring the search (estimate)."
                        ),
                    )
                )
    return findings


def rule_non_sargable_function(
    expression: exp.Expression, schema: NormalizedSchema | None
) -> list[Optimization]:
    """Flag functions wrapped around filter columns (non-sargable predicates)."""
    findings: list[Optimization] = []
    seen: set[str] = set()
    for select in expression.find_all(exp.Select):
        where = select.args.get("where")
        if where is None:
            continue
        for func in where.find_all(exp.Func):
            inner_columns = list(func.find_all(exp.Column))
            if not inner_columns:
                continue
            label = func.sql()
            if label in seen:
                continue
            seen.add(label)
            findings.append(
                Optimization(
                    rule="non-sargable-function",
                    severity="warning",
                    message=(
                        f"Function call {label} wraps a column in the WHERE clause, "
                        "which prevents index use. Rewrite the predicate so the "
                        "column is compared directly, or add a matching expression "
                        "index (estimate)."
                    ),
                )
            )
    return findings


def rule_missing_join_condition(
    expression: exp.Expression, schema: NormalizedSchema | None
) -> list[Optimization]:
    """Detect implicit cross joins / joins missing an ON (or USING) condition."""
    findings: list[Optimization] = []
    for join in expression.find_all(exp.Join):
        if join.kind == "CROSS":
            # Explicit CROSS JOIN is intentional; do not flag.
            continue
        has_on = join.args.get("on") is not None
        has_using = bool(join.args.get("using"))
        if not has_on and not has_using:
            findings.append(
                Optimization(
                    rule="missing-join-condition",
                    severity="warning",
                    message=(
                        "A join has no ON/USING condition, producing an implicit "
                        "cross join (cartesian product). Add a join condition or use "
                        "an explicit CROSS JOIN if intended."
                    ),
                )
            )
    return findings


def rule_unbounded_select(
    expression: exp.Expression, schema: NormalizedSchema | None
) -> list[Optimization]:
    """Suggest a LIMIT for unbounded exploratory SELECTs."""
    findings: list[Optimization] = []
    # Only consider top-level SELECT statements (not INSERT/CREATE sub-selects).
    if not isinstance(expression, exp.Select):
        return findings
    if expression.args.get("limit") is not None:
        return findings
    # Aggregates without GROUP BY return a single row, so a LIMIT is pointless.
    has_aggregate = any(expression.find_all(exp.AggFunc))
    has_group = expression.args.get("group") is not None
    if has_aggregate and not has_group:
        return findings
    findings.append(
        Optimization(
            rule="unbounded-select",
            severity="info",
            message=(
                "Exploratory SELECT has no LIMIT. Add a LIMIT to cap the result set "
                "when you only need a sample (estimate)."
            ),
        )
    )
    return findings


class RuleBasedOptimizer:
    """Applies the deterministic optimization rules to a SQL statement."""

    #: The ordered set of rules applied by :meth:`optimize`.
    RULES: tuple[Rule, ...] = (
        rule_select_star,
        rule_missing_where,
        rule_index_suggestions,
        rule_leading_wildcard_like,
        rule_non_sargable_function,
        rule_missing_join_condition,
        rule_unbounded_select,
    )

    def optimize(
        self,
        sql: str,
        dialect: str | None = None,
        schema: NormalizedSchema | None = None,
    ) -> list[Optimization]:
        """Return all rule findings for ``sql``.

        Returns an empty list when the SQL cannot be parsed (syntax validation
        is the validator's responsibility). No SQL is ever executed.
        """
        read = normalize_dialect(dialect)
        try:
            statements = sqlglot.parse(sql, read=read)
        except Exception:  # noqa: BLE001 - parse errors are not optimizer errors
            return []

        findings: list[Optimization] = []
        for statement in statements:
            if statement is None:
                continue
            for rule in self.RULES:
                findings.extend(rule(statement, schema))
        return findings

    def rewritten_sql(self, optimizations: list[Optimization]) -> str | None:
        """Return the first concrete rewrite proposed by any rule, if any."""
        for opt in optimizations:
            if opt.rewritten_sql:
                return opt.rewritten_sql
        return None
