"""Deterministic diff between two persisted decisions. No LLM, no retrieval."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.decisions.models import Decision, Level


class DecisionComparison(BaseModel):
    left_decision_id: str
    right_decision_id: str
    # Right supersedes left, directly or transitively via the chain we can see.
    right_supersedes_left: bool = False
    recommendation_changed: bool = False
    left_recommendation: str = ""
    right_recommendation: str = ""
    confidence_changed: bool = False
    left_confidence: Level = Level.MEDIUM
    right_confidence: Level = Level.MEDIUM
    status_changed: bool = False
    left_status: str = ""
    right_status: str = ""
    added_evidence: list[str] = Field(default_factory=list)
    removed_evidence: list[str] = Field(default_factory=list)
    added_claims: list[str] = Field(default_factory=list)
    removed_claims: list[str] = Field(default_factory=list)
    added_assumptions: list[str] = Field(default_factory=list)
    removed_assumptions: list[str] = Field(default_factory=list)
    added_risks: list[str] = Field(default_factory=list)
    removed_risks: list[str] = Field(default_factory=list)
    added_alternatives: list[str] = Field(default_factory=list)
    removed_alternatives: list[str] = Field(default_factory=list)
    changed_since_previous: list[str] = Field(default_factory=list)


def _diff(left: list[str], right: list[str]) -> tuple[list[str], list[str]]:
    """Added and removed, compared as sets but returned in the source order
    so two runs over the same pair produce byte-identical output."""
    left_set, right_set = set(left), set(right)
    added = [item for item in dict.fromkeys(right) if item not in left_set]
    removed = [item for item in dict.fromkeys(left) if item not in right_set]
    return added, removed


def compare_decisions(left: Decision, right: Decision) -> DecisionComparison:
    """Compare two decisions field by field.

    Evidence is compared on its statement rather than its evidence_id: ids are
    assigned per analysis run (E1, E2, ...) and carry no meaning across
    decisions, so comparing them would report every decision as fully changed.
    """
    added_evidence, removed_evidence = _diff(
        [e.statement for e in left.evidence], [e.statement for e in right.evidence]
    )
    added_claims, removed_claims = _diff(
        [c.statement for c in left.claims], [c.statement for c in right.claims]
    )
    added_assumptions, removed_assumptions = _diff(
        [a.statement for a in left.assumptions], [a.statement for a in right.assumptions]
    )
    added_risks, removed_risks = _diff(
        [r.statement for r in left.risks], [r.statement for r in right.risks]
    )
    added_alternatives, removed_alternatives = _diff(
        [a.name for a in left.alternatives], [a.name for a in right.alternatives]
    )
    return DecisionComparison(
        left_decision_id=left.decision_id,
        right_decision_id=right.decision_id,
        right_supersedes_left=right.supersedes == left.decision_id,
        recommendation_changed=(
            left.recommendation.statement != right.recommendation.statement
        ),
        left_recommendation=left.recommendation.statement,
        right_recommendation=right.recommendation.statement,
        confidence_changed=(
            left.recommendation.confidence != right.recommendation.confidence
        ),
        left_confidence=left.recommendation.confidence,
        right_confidence=right.recommendation.confidence,
        status_changed=left.status != right.status,
        left_status=left.status.value,
        right_status=right.status.value,
        added_evidence=added_evidence,
        removed_evidence=removed_evidence,
        added_claims=added_claims,
        removed_claims=removed_claims,
        added_assumptions=added_assumptions,
        removed_assumptions=removed_assumptions,
        added_risks=added_risks,
        removed_risks=removed_risks,
        added_alternatives=added_alternatives,
        removed_alternatives=removed_alternatives,
        changed_since_previous=list(right.changed_since_previous),
    )
