"""Deterministic SQL validation built on SQLGlot.

This module provides *static* validation only. It parses SQL into a SQLGlot AST
and inspects that AST; it NEVER executes user-entered or AI-generated SQL. All
schema-aware checks compare AST references against the cached normalized schema.

Two layers of validation are offered:

* :meth:`SqlValidator.validate_syntax` - parses one or more statements across the
  supported dialects and reports structured syntax errors plus a classification
  of each statement.
* :meth:`SqlValidator.validate_against_schema` - walks a parsed AST, resolving
  CTE names and table aliases (which are not schema errors), and flags unknown
  tables / columns against a :class:`NormalizedSchema`.

:meth:`SqlValidator.validate` combines both layers into a single
:class:`ValidationResult`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.models.api_models import ValidationResult
from app.models.schema_models import NormalizedSchema

# Friendly dialect names mapped to the SQLGlot dialect identifier.
_DIALECT_MAP: dict[str, str] = {
    "postgres": "postgres",
    "postgresql": "postgres",
    "pg": "postgres",
    "mysql": "mysql",
    "mariadb": "mysql",
    "tsql": "tsql",
    "sqlserver": "tsql",
    "mssql": "tsql",
    "sqlite": "sqlite",
    "oracle": "oracle",
}


def normalize_dialect(dialect: str | None) -> str:
    """Map a friendly dialect name to a SQLGlot dialect identifier.

    Unknown or empty dialects fall back to ``postgres`` which is the project
    default. The mapping is case-insensitive.
    """
    if not dialect:
        return "postgres"
    return _DIALECT_MAP.get(dialect.strip().lower(), "postgres")


@dataclass
class ParsedStatement:
    """A single parsed statement and its classification."""

    index: int
    statement_type: str
    expression: exp.Expression


@dataclass
class SyntaxCheckResult:
    """Outcome of parsing a (possibly multi-statement) SQL string."""

    statements: list[ParsedStatement] = field(default_factory=list)
    syntax_errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.syntax_errors


class SqlValidator:
    """Static SQL validator over the SQLGlot AST.

    The validator performs no SQL execution of any kind; it is pure analysis of
    the parsed abstract syntax tree plus the normalized schema.
    """

    def parse(self, sql: str, dialect: str | None = None) -> list[exp.Expression]:
        """Parse ``sql`` into a list of statement expressions.

        Raises :class:`sqlglot.errors.ParseError` on malformed SQL. Empty
        statements (produced by trailing semicolons) are filtered out.
        """
        read = normalize_dialect(dialect)
        parsed = sqlglot.parse(sql, read=read)
        return [stmt for stmt in parsed if stmt is not None]

    @staticmethod
    def _classify(expression: exp.Expression) -> str:
        """Return a human-friendly statement type for an expression."""
        return type(expression).__name__.upper()

    @staticmethod
    def _format_parse_error(error: ParseError) -> list[str]:
        """Turn a SQLGlot ParseError into human-readable message strings."""
        messages: list[str] = []
        details = getattr(error, "errors", None) or []
        for detail in details:
            description = detail.get("description", "Syntax error")
            line = detail.get("line")
            col = detail.get("col")
            if line is not None and col is not None:
                messages.append(f"{description} (line {line}, col {col})")
            else:
                messages.append(str(description))
        if not messages:
            messages.append(str(error).splitlines()[0])
        return messages

    def validate_syntax(self, sql: str, dialect: str | None = None) -> SyntaxCheckResult:
        """Parse ``sql`` and return statements + structured syntax errors."""
        result = SyntaxCheckResult()
        if not sql or not sql.strip():
            result.syntax_errors.append("Empty SQL statement")
            return result

        try:
            expressions = self.parse(sql, dialect)
        except ParseError as exc:
            result.syntax_errors.extend(self._format_parse_error(exc))
            return result

        for idx, expression in enumerate(expressions):
            result.statements.append(
                ParsedStatement(
                    index=idx,
                    statement_type=self._classify(expression),
                    expression=expression,
                )
            )
        return result

    # -- Schema-aware validation ------------------------------------------------

    @staticmethod
    def _schema_lookup(schema: NormalizedSchema) -> dict[str, set[str]]:
        """Build a case-insensitive {table_name: {column_names}} lookup."""
        lookup: dict[str, set[str]] = {}
        for table in schema.tables:
            lookup[table.name.lower()] = {col.name.lower() for col in table.columns}
        return lookup

    @staticmethod
    def _collect_scope_names(expression: exp.Expression) -> tuple[set[str], set[str]]:
        """Collect names that are *not* real schema tables.

        Returns ``(cte_names, alias_names)`` where both sets are lower-cased.
        CTE names and table / subquery aliases are local scope names and must
        never be reported as unknown tables.
        """
        cte_names: set[str] = set()
        for cte in expression.find_all(exp.CTE):
            if cte.alias:
                cte_names.add(cte.alias.lower())

        alias_names: set[str] = set()
        for alias in expression.find_all(exp.TableAlias):
            if alias.name:
                alias_names.add(alias.name.lower())
        # Derived-table / subquery aliases also appear as Subquery.alias.
        for subquery in expression.find_all(exp.Subquery):
            if subquery.alias:
                alias_names.add(subquery.alias.lower())
        return cte_names, alias_names

    @staticmethod
    def _created_table_name(expression: exp.Expression) -> str | None:
        """Return the lower-cased name of a table/view defined by a CREATE.

        For ``CREATE TABLE foo (...)`` (and ``CREATE TABLE foo AS SELECT ...``)
        ``foo`` is a *new* object being defined, not a reference to an existing
        schema table, so it must not be flagged as an unknown table. The columns
        declared in its definition are likewise new and must not be checked
        against the base schema. ``CREATE INDEX ... ON existing_table`` is not a
        table definition, so its ``ON`` target is still validated normally.
        """
        if not isinstance(expression, exp.Create):
            return None
        if (expression.kind or "").upper() not in ("TABLE", "VIEW"):
            return None
        target = expression.this
        # ``CREATE TABLE foo (...)`` -> this is a Schema wrapping the Table;
        # ``CREATE TABLE foo AS SELECT`` -> this is the Table directly.
        if isinstance(target, exp.Schema):
            target = target.this
        if isinstance(target, exp.Table):
            return target.name.lower()
        return None

    def validate_against_schema(
        self,
        parsed: exp.Expression,
        schema: NormalizedSchema,
    ) -> tuple[list[str], list[str]]:
        """Return ``(schema_errors, warnings)`` for one parsed statement.

        * Unknown real tables and unknown columns become schema errors.
        * CTE names and aliases are treated as valid local scopes.
        * Columns referenced without a table qualifier in a multi-table query,
          or ambiguous columns, become warnings.

        No SQL is executed; this is pure AST + schema analysis.
        """
        schema_errors: list[str] = []
        warnings: list[str] = []

        table_columns = self._schema_lookup(schema)
        cte_names, _alias_names = self._collect_scope_names(parsed)

        # A table defined by this statement (CREATE TABLE/VIEW) is a brand-new
        # object, not a reference to an existing schema table. Treat it as a
        # local scope so neither the table nor its freshly declared columns are
        # reported as "unknown". Tables referenced by a CREATE ... AS SELECT are
        # still validated because only the created name is excluded here.
        created_table = self._created_table_name(parsed)
        local_scope_names: set[str] = set(cte_names)
        if created_table is not None:
            local_scope_names.add(created_table)

        # Map an alias (or table name used as its own alias) -> real table name,
        # so qualified columns can be checked against the right table.
        alias_to_table: dict[str, str] = {}
        real_tables_in_query: set[str] = set()
        # Qualifiers that resolve to a CTE/derived scope (columns are produced
        # by a subquery and cannot be checked against the base schema).
        scope_qualifiers: set[str] = set(local_scope_names)

        for table in parsed.find_all(exp.Table):
            name = table.name.lower()
            is_real = name in table_columns
            is_scope = name in local_scope_names
            if not is_real and not is_scope:
                schema_errors.append(f"Unknown table: {table.name}")
                continue
            alias = (table.alias or table.name).lower()
            if is_real:
                real_tables_in_query.add(name)
                alias_to_table[alias] = name
            else:
                # CTE scope referenced (possibly via an alias): skip its columns.
                scope_qualifiers.add(alias)

        multi_table = len(real_tables_in_query) > 1

        for column in parsed.find_all(exp.Column):
            col_name = column.name.lower()
            qualifier = column.table.lower() if column.table else ""

            if qualifier:
                if qualifier in scope_qualifiers:
                    # Column resolved against a CTE / derived-table scope: not a
                    # schema error (its columns come from the subquery/CTE).
                    continue
                real_table = alias_to_table.get(qualifier)
                if real_table is None:
                    # Qualifier is not a known table/alias in this query.
                    schema_errors.append(f"Unknown table alias: {column.table}")
                    continue
                if col_name not in table_columns.get(real_table, set()):
                    schema_errors.append(f"Unknown column: {column.table}.{column.name}")
                continue

            # Unqualified column.
            owning_tables = [
                tbl for tbl in real_tables_in_query if col_name in table_columns.get(tbl, set())
            ]
            if not owning_tables:
                # The column is not found in any real table in scope. Only flag
                # as an error when every source is a concrete schema table (a
                # CTE / derived table could legitimately expose this column).
                has_scope_source = bool(scope_qualifiers)
                if real_tables_in_query and not has_scope_source:
                    schema_errors.append(f"Unknown column: {column.name}")
                continue
            if multi_table and len(owning_tables) > 1:
                warnings.append(
                    f"Ambiguous column '{column.name}' matches multiple tables; "
                    "qualify it with a table name"
                )
            elif multi_table:
                warnings.append(
                    f"Column '{column.name}' referenced without a table qualifier "
                    "in a multi-table query"
                )

        return schema_errors, warnings

    # -- Combined entry point ---------------------------------------------------

    def validate(
        self,
        sql: str,
        dialect: str | None = None,
        schema: NormalizedSchema | None = None,
    ) -> ValidationResult:
        """Validate syntax and, when a schema is given, schema references.

        Returns a :class:`ValidationResult`. ``is_valid`` is True only when
        there are no syntax errors and no schema errors.
        """
        syntax = self.validate_syntax(sql, dialect)
        result = ValidationResult(
            syntax_errors=list(syntax.syntax_errors),
            parsed_statements=len(syntax.statements),
        )

        if syntax.syntax_errors:
            result.is_valid = False
            return result

        if schema is not None:
            seen_warnings: set[str] = set()
            for stmt in syntax.statements:
                errors, warnings = self.validate_against_schema(stmt.expression, schema)
                result.schema_errors.extend(errors)
                for warning in warnings:
                    if warning not in seen_warnings:
                        seen_warnings.add(warning)
                        result.warnings.append(warning)

        result.is_valid = not result.syntax_errors and not result.schema_errors
        return result
