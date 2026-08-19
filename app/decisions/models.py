"""Structured decision domain.

Pydantic models because these objects cross three boundaries — the LLM's
structured output, the HTTP API, and the on-disk decision record — and one
schema for all three keeps them from drifting apart.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.domain import utcnow


class Level(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DecisionStatus(str, Enum):
    PROPOSED = "proposed"
    REASSESSED = "reassessed"


class Evidence(BaseModel):
    evidence_id: str
    statement: str
    source: str | None = None
    relevance: Level = Level.MEDIUM


class Claim(BaseModel):
    statement: str
    supporting_evidence: list[str] = Field(default_factory=list)


class Assumption(BaseModel):
    statement: str
    confidence: Level = Level.MEDIUM


class Risk(BaseModel):
    statement: str
    severity: Level = Level.MEDIUM
    rationale: str = ""


class Alternative(BaseModel):
    name: str
    description: str = ""
    advantages: list[str] = Field(default_factory=list)
    disadvantages: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    statement: str
    rationale: str = ""
    confidence: Level = Level.MEDIUM


class Decision(BaseModel):
    """A complete, evidence-backed decision analysis."""

    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    workspace_id: str
    session_id: str
    question: str
    status: DecisionStatus = DecisionStatus.PROPOSED
    created_at: datetime = Field(default_factory=utcnow)
    recommendation: Recommendation
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    # Set when this analysis revisits an earlier decision.
    supersedes: str | None = None
    changed_since_previous: list[str] = Field(default_factory=list)

    def as_memory_text(self) -> str:
        """Human-readable form written into Cognee memory.

        Cognee indexes this so a later question can surface the decision
        semantically; the authoritative structured copy lives in the store.
        """
        lines = [
            f"Decision ({self.status.value}) recorded {self.created_at.isoformat()}",
            f"Question: {self.question}",
            f"Recommendation: {self.recommendation.statement}",
            f"Rationale: {self.recommendation.rationale}",
            f"Confidence: {self.recommendation.confidence.value}",
        ]
        for label, items in (
            ("Claims", [c.statement for c in self.claims]),
            ("Assumptions", [a.statement for a in self.assumptions]),
            ("Risks", [r.statement for r in self.risks]),
            ("Alternatives", [a.name for a in self.alternatives]),
            ("Sources", self.sources),
        ):
            if items:
                lines.append(f"{label}: " + "; ".join(items))
        return "\n".join(lines)

    def as_previous_context(self) -> str:
        """Compact form fed back into a reassessment prompt."""
        return (
            f"[{self.decision_id}] {self.created_at.date().isoformat()} "
            f"Q: {self.question} | Recommendation: {self.recommendation.statement} "
            f"({self.recommendation.confidence.value}) | "
            f"Assumptions: {'; '.join(a.statement for a in self.assumptions) or 'none'} | "
            f"Risks: {'; '.join(r.statement for r in self.risks) or 'none'}"
        )


# --- LLM structured-output envelopes ---------------------------------------
# Each analysis stage asks the model for exactly one of these shapes.


class EvidenceSet(BaseModel):
    evidence: list[Evidence] = Field(default_factory=list)


class ClaimSet(BaseModel):
    claims: list[Claim] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    assumptions: list[Assumption] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)


class AlternativeSet(BaseModel):
    alternatives: list[Alternative] = Field(default_factory=list)


class RecommendationResult(BaseModel):
    recommendation: Recommendation
    changed_since_previous: list[str] = Field(default_factory=list)


def json_schema_hint(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()
