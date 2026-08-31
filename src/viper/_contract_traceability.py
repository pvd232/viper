"""Define contract-requirement traceability records."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from ._schema import NonEmptyStr, ProtocolModel, RepoRelPath

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
    checklist_line: int = Field(
        ge=1,
        description="One-based checklist line that declares this relationship.",
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


class ContractTraceCase(ProtocolModel):
    """Trace one rule through a concrete accepted or rejected case."""

    trace_id: TraceId = Field(
        description="Stable identifier of this concrete trace case."
    )
    requirement_id: RequirementId = Field(
        description="Contract requirement demonstrated by the case."
    )
    rule_id: VerifierRuleId = Field(
        description="Verifier rule exercised by the case."
    )
    state: TraceState = Field(
        description="Whether the referenced implementation and test exist."
    )
    scenario: NonEmptyStr = Field(
        description="One behavior demonstrated by the case."
    )
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
        description="Accepted result or rejected failure expected from the case."
    )


class ContractTraceabilityGraph(ProtocolModel):
    """Store the complete ordered traceability graph."""

    schema_version: Literal[1] = Field(
        default=1,
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
    traces: tuple[ContractTraceCase, ...] = Field(
        min_length=1,
        description="Ordered accepted and rejected trace cases.",
    )
