"""Define contract-requirement traceability records."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ._schema import SHA256, NonEmptyStr, ProtocolModel, RepoRelPath

RequirementId = Annotated[
    str,
    Field(pattern=r"^[A-Z]{3}-[0-9]{2}$"),
]
VerifierRuleId = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"),
]
TraceId = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9-]+$"),
]

RuleEdgeKind = Literal["implementation", "verification"]
TraceState = Literal["planned", "implemented"]


class DeclarationRef(ProtocolModel):
    """Locate and identify one authored traceability declaration."""

    path: RepoRelPath = Field(
        description="Repository-relative document containing the declaration."
    )
    start_line: int = Field(
        ge=1,
        description="One-based first line occupied by the declaration.",
    )
    end_line: int = Field(
        ge=1,
        description="One-based final line occupied by the declaration.",
    )
    sha256: SHA256 = Field(
        description="SHA-256 digest of the exact UTF-8 declaration bytes."
    )

    @model_validator(mode="after")
    def validate_line_order(self) -> Self:
        """Require the final line to include or follow the first line."""
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class RepoSymbolRef(ProtocolModel):
    """Reference one qualified symbol in one repository file."""

    path: RepoRelPath = Field(
        description="Repository-relative source file containing the symbol."
    )
    symbol: NonEmptyStr = Field(
        description="Qualified symbol name resolved inside the source file."
    )


class ContractRequirement(ProtocolModel):
    """Identify one requirement declared by one contract."""

    requirement_id: RequirementId = Field(
        description="Stable identifier declared by the owning contract."
    )
    contract: RepoRelPath = Field(
        description="Repository-relative contract that declares the requirement."
    )
    declaration: DeclarationRef = Field(
        description="Exact authored requirement marker used to reconstruct this record."
    )


class VerifierRule(ProtocolModel):
    """Declare one testable rule required by a contract."""

    rule_id: VerifierRuleId = Field(
        description="Stable identifier of the executable invariant."
    )
    requirement_id: RequirementId = Field(
        description="Contract requirement that owns the verifier rule."
    )
    contract: RepoRelPath = Field(
        description="Repository-relative contract that declares the rule."
    )
    statement: NonEmptyStr = Field(
        description="Testable invariant enforced by the rule."
    )
    declaration: DeclarationRef = Field(
        description=(
            "Exact authored verifier-rule marker used to reconstruct this record."
        )
    )


class RuleEdge(ProtocolModel):
    """Connect one verifier rule to an implementation or test."""

    kind: RuleEdgeKind = Field(
        description="Relationship from the rule to an implementation or test."
    )
    rule_id: VerifierRuleId = Field(
        description="Verifier rule at the source of this edge."
    )
    phase: int = Field(
        ge=0,
        description="Checklist phase that schedules this relationship.",
    )
    declaration: DeclarationRef = Field(
        description="Exact checklist marker that declares this relationship."
    )
    state: TraceState = Field(
        description="Whether the referenced symbol is planned or implemented."
    )
    target: RepoSymbolRef = Field(
        description="Repository symbol reached by this relationship."
    )


class AcceptedTraceOutcome(ProtocolModel):
    """Describe the result and evidence produced by an accepted trace."""

    kind: Literal["accepted"] = Field(
        default="accepted",
        description="Discriminator for a successful trace.",
    )
    result: NonEmptyStr = Field(
        description="Value or state the successful invocation must produce."
    )
    evidence: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description="Durable records or artifacts that prove the result occurred.",
    )


class RejectedTraceOutcome(ProtocolModel):
    """Describe the failure expected from a rejected trace."""

    kind: Literal["rejected"] = Field(
        default="rejected",
        description="Discriminator for a rejected trace.",
    )
    rejected_at: RepoSymbolRef = Field(
        description="Exact code symbol that must reject the input."
    )
    error_type: NonEmptyStr = Field(
        description="Exception type the caller must receive."
    )
    message_match: NonEmptyStr = Field(
        description="Stable error-message text the test must observe."
    )


TraceOutcome = Annotated[
    AcceptedTraceOutcome | RejectedTraceOutcome,
    Field(discriminator="kind"),
]


class ContractTrace(ProtocolModel):
    """Record one concrete accepted or rejected execution of a verifier rule."""

    trace_id: TraceId = Field(description="Stable identifier of this concrete trace.")
    requirement_id: RequirementId = Field(
        description="Contract requirement demonstrated by the trace."
    )
    rule_id: VerifierRuleId = Field(description="Verifier rule exercised by the trace.")
    state: TraceState = Field(
        description="Whether the referenced implementation and test exist."
    )
    scenario: NonEmptyStr = Field(description="One behavior demonstrated by the trace.")
    setup: NonEmptyStr = Field(
        description="Concrete state established before the invocation."
    )
    input: NonEmptyStr = Field(
        description="Exact authored value or declaration processed by the invocation."
    )
    invocation: NonEmptyStr = Field(
        description="Exact function call or command that processes the input."
    )
    implementation: RepoSymbolRef = Field(
        description="Source symbol that implements the exercised behavior."
    )
    test: RepoSymbolRef = Field(
        description="Test function that observes the expected outcome."
    )
    outcome: TraceOutcome = Field(
        description="Accepted result or rejected failure expected from the trace."
    )
    declaration: DeclarationRef = Field(
        description="Exact contract-trace fence used to reconstruct this record."
    )


class ContractTraceabilityGraph(ProtocolModel):
    """Store the complete ordered traceability graph."""

    schema_version: Literal[2] = Field(
        default=2,
        description="Format version of the serialized traceability graph.",
    )
    requirements: tuple[ContractRequirement, ...] = Field(
        min_length=1,
        description="Ordered contract requirements represented by the graph.",
    )
    rules: tuple[VerifierRule, ...] = Field(
        min_length=1,
        description="Ordered verifier rules represented by the graph.",
    )
    edges: tuple[RuleEdge, ...] = Field(
        min_length=1,
        description="Ordered implementation and verification relationships.",
    )
    traces: tuple[ContractTrace, ...] = Field(
        min_length=1,
        description="Ordered accepted and rejected traces.",
    )
