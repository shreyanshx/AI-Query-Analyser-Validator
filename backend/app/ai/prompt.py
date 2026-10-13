"""Prompt construction and response parsing for the AI layer.

:class:`PromptContext` carries only non-sensitive inputs: the user's SQL, the
dialect, and a normalized schema *summary* (table / column / index names).
Database credentials and raw sampled values are NEVER included - the only
schema context is the opt-in structural metadata already introspected by the
schema service.

:func:`build_prompt` renders a strict-JSON instruction prompt. :func:`parse_response`
extracts the JSON object the model returns and maps it to an :class:`AISuggestion`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.models.schema_models import NormalizedSchema

# Keys a well-formed model response is expected to contain.
_SUGGESTED_SQL_KEYS = ("suggested_sql", "sql", "optimized_sql", "corrected_sql")
_EXPLANATION_KEYS = ("explanation", "reason", "rationale")
_OPTIMIZATIONS_KEYS = ("optimizations", "changes", "suggestions")

_SYSTEM_INSTRUCTIONS = (
    "You are a careful SQL optimization assistant. Given a SQL statement, its "
    "dialect, and a database schema summary, return a corrected and optimized "
    "version of the SQL together with a short explanation and a list of the "
    "specific optimizations you applied. Preserve the original semantics. Do "
    "NOT invent tables or columns that are not in the provided schema. Respond "
    "with STRICT JSON only (no markdown fences, no prose outside the JSON) using "
    'exactly these keys: {"suggested_sql": string, "explanation": string, '
    '"optimizations": array of strings}.'
)


@dataclass
class PromptContext:
    """Non-sensitive inputs used to build an AI prompt.

    Only structural schema metadata is included. No credentials, connection
    strings, or sampled row values are ever placed here.
    """

    sql: str
    dialect: str = "postgres"
    schema_summary: str | None = None

    @classmethod
    def from_schema(
        cls,
        sql: str,
        dialect: str = "postgres",
        schema: NormalizedSchema | None = None,
    ) -> PromptContext:
        """Build a context, summarizing ``schema`` to structural metadata only."""
        summary = summarize_schema(schema) if schema is not None else None
        return cls(sql=sql, dialect=dialect, schema_summary=summary)


def summarize_schema(schema: NormalizedSchema) -> str:
    """Render a compact, non-sensitive schema summary.

    Includes table names, column names + types, primary keys, and index
    columns. Contains no credentials and no data values.
    """
    lines: list[str] = []
    for table in schema.tables:
        cols = ", ".join(
            f"{col.name} {col.data_type}" + (" PK" if col.is_primary_key else "")
            for col in table.columns
        )
        lines.append(f"- {table.name}({cols})")
        for index in table.indexes:
            kind = "unique index" if index.unique else "index"
            lines.append(f"    {kind} {index.name} on ({', '.join(index.columns)})")
    if not lines:
        return "(no schema metadata available)"
    return "\n".join(lines)


def build_prompt(context: PromptContext) -> str:
    """Render the full prompt string from a :class:`PromptContext`."""
    schema_block = context.schema_summary or "(no schema provided; validate syntax only)"
    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        f"Dialect: {context.dialect}\n\n"
        f"Schema:\n{schema_block}\n\n"
        f"SQL to optimize:\n{context.sql}\n\n"
        "Return STRICT JSON now."
    )


def _extract_json_object(text: str) -> dict:
    """Extract the first JSON object from ``text``.

    Tolerates markdown code fences and leading/trailing prose by locating the
    first balanced ``{...}`` block when a direct parse fails.
    """
    stripped = text.strip()
    # Strip common ```json ... ``` fences.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()

    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Fall back to locating the first balanced object.
    start = stripped.find("{")
    while start != -1:
        depth = 0
        for end in range(start, len(stripped)):
            char = stripped[end]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = stripped[start : end + 1]
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break
        start = stripped.find("{", start + 1)

    raise ValueError("No JSON object found in model response")


def _first_key(data: dict, keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def parse_response(text: str, provider: str) -> tuple[str, str, list[str]]:
    """Parse a raw model text response into suggestion fields.

    Returns a tuple ``(suggested_sql, explanation, optimizations)``. Raises
    :class:`ValueError` when no suggested SQL can be extracted. The provider
    adapter wraps this into an :class:`~app.ai.base.AISuggestion`.
    """
    data = _extract_json_object(text)

    suggested = _first_key(data, _SUGGESTED_SQL_KEYS)
    if not isinstance(suggested, str) or not suggested.strip():
        raise ValueError(f"{provider} response missing suggested SQL")

    explanation_val = _first_key(data, _EXPLANATION_KEYS)
    explanation = explanation_val if isinstance(explanation_val, str) else ""

    optimizations_val = _first_key(data, _OPTIMIZATIONS_KEYS)
    optimizations: list[str] = []
    if isinstance(optimizations_val, list):
        optimizations = [str(item) for item in optimizations_val]
    elif isinstance(optimizations_val, str) and optimizations_val.strip():
        optimizations = [optimizations_val.strip()]

    return suggested.strip(), explanation, optimizations
