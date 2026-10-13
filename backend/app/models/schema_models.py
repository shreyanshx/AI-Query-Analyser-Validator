"""Normalized database schema models.

These models describe schema metadata in a database-agnostic way so that the
validator, optimizer, and AI layers can consume a single normalized shape
regardless of the source dialect.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Column(BaseModel):
    """A single table column."""

    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    is_primary_key: bool = False


class Index(BaseModel):
    """An index defined on a table."""

    name: str
    columns: list[str] = Field(default_factory=list)
    unique: bool = False


class ForeignKey(BaseModel):
    """A foreign key relationship."""

    name: str | None = None
    columns: list[str] = Field(default_factory=list)
    referenced_table: str = ""
    referenced_columns: list[str] = Field(default_factory=list)


class Table(BaseModel):
    """A table (or view) and its columns, indexes, and foreign keys."""

    name: str
    schema_name: str | None = None
    columns: list[Column] = Field(default_factory=list)
    indexes: list[Index] = Field(default_factory=list)
    foreign_keys: list[ForeignKey] = Field(default_factory=list)
    row_estimate: int | None = None


class Schema(BaseModel):
    """A normalized schema: the collection of tables for a database."""

    dialect: str
    database: str | None = None
    tables: list[Table] = Field(default_factory=list)

    def table_names(self) -> list[str]:
        return [t.name for t in self.tables]


# Public alias used across the codebase for the normalized schema type.
NormalizedSchema = Schema
