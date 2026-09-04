"""Model the three cached stages that produce a source graph.

SourceSnapshot + ExtractionSpec -> DatabaseReceipt
DatabaseReceipt + QuerySpec -> QueryReceipt
QueryReceipt + GraphFormat -> GraphReceipt

Each stage derives its key from the exact inputs it consumes. Changing queries
can reuse the database. Changing graph construction can reuse query results.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from viper._schema import SHA256, NonEmptyStr, ProtocolModel
from viper.system_impact.models import SourceSnapshot


class ExtractionSpec(ProtocolModel):
    """Identify the CodeQL installation and extraction mode."""

    version: NonEmptyStr = Field(description="CodeQL CLI version.")
    platform: NonEmptyStr = Field(description="CodeQL bundle platform.")
    executable_sha256: SHA256 = Field(description="Digest of the CodeQL executable.")
    extractor_sha256: SHA256 = Field(description="Digest of the Python extractor tree.")
    language: Literal["python"] = Field(
        default="python",
        description="Language extracted into the database.",
    )
    build_mode: Literal["none"] = Field(
        default="none",
        description="CodeQL database build mode.",
    )


class QuerySpec(ProtocolModel):
    """Identify the query pack and suite executed against a database."""

    pack: NonEmptyStr = Field(description="Query-pack name and version.")
    pack_sha256: SHA256 = Field(description="Digest of the query-pack tree.")
    suite: NonEmptyStr = Field(description="Query suite selected from the pack.")


class GraphFormat(ProtocolModel):
    """Identify the graph schema and CodeQL-row conversion rules."""

    schema_version: int = Field(
        ge=1,
        description="Serialized SourceGraph format version.",
    )
    lowering_version: int = Field(
        ge=1,
        description="Version of the rules that convert query rows into the graph.",
    )


class DatabaseReceipt(ProtocolModel):
    """Record one completed source extraction."""

    snapshot: SourceSnapshot = Field(description="Source extracted by CodeQL.")
    extraction: ExtractionSpec = Field(description="Extraction settings used.")
    key: SHA256 = Field(description="Digest of the snapshot and extraction settings.")
    sha256: SHA256 = Field(description="Digest of the created database tree.")
    commands: tuple[tuple[NonEmptyStr, ...], ...] = Field(
        min_length=1,
        description="Commands executed to create the database.",
    )
    exit_code: int = Field(description="Database-creation process exit code.")
    stderr_sha256: SHA256 = Field(description="Digest of captured standard error.")


class QueryReceipt(ProtocolModel):
    """Record one completed query-suite execution."""

    database_key: SHA256 = Field(description="Key of the database queried.")
    database_sha256: SHA256 = Field(description="Digest of that database tree.")
    query: QuerySpec = Field(description="Query pack and suite executed.")
    key: SHA256 = Field(description="Digest of the database and query specification.")
    sha256: SHA256 = Field(description="Digest of the complete BQRS result tree.")
    commands: tuple[tuple[NonEmptyStr, ...], ...] = Field(
        min_length=1,
        description="Commands executed to produce the query results.",
    )
    exit_code: int = Field(description="Query process exit code.")
    stderr_sha256: SHA256 = Field(description="Digest of captured standard error.")


class GraphReceipt(ProtocolModel):
    """Record the conversion of one query result into a source graph."""

    query_key: SHA256 = Field(description="Key of the query results converted.")
    query_sha256: SHA256 = Field(description="Digest of the BQRS result tree.")
    format: GraphFormat = Field(description="Graph schema and conversion rules used.")
    key: SHA256 = Field(description="Digest of the query results and graph format.")
    sha256: SHA256 = Field(description="Digest of the serialized SourceGraph.")


__all__ = [
    "DatabaseReceipt",
    "ExtractionSpec",
    "GraphFormat",
    "GraphReceipt",
    "QueryReceipt",
    "QuerySpec",
]
