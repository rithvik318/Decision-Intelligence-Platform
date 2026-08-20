"""Recommendation -> claims -> evidence -> source, read off a stored decision.

Nothing is inferred or re-retrieved: every link comes from the decision as it
was persisted, and a claim citing an evidence id the decision does not contain
is reported as unresolved rather than quietly dropped or invented.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.decisions.models import Decision, Level


class ProvenanceEvidence(BaseModel):
    evidence_id: str
    statement: str
    source: str | None = None
    relevance: Level = Level.MEDIUM


class ProvenanceClaim(BaseModel):
    statement: str
    evidence: list[ProvenanceEvidence] = Field(default_factory=list)
    # Evidence ids cited by the claim that the decision does not contain.
    unresolved_evidence_ids: list[str] = Field(default_factory=list)


class ProvenanceRecommendation(BaseModel):
    statement: str
    rationale: str = ""
    confidence: Level = Level.MEDIUM
    claims: list[ProvenanceClaim] = Field(default_factory=list)


class DecisionProvenance(BaseModel):
    decision_id: str
    workspace_id: str
    question: str
    recommendation: ProvenanceRecommendation
    sources: list[str] = Field(default_factory=list)
    # Evidence the decision holds that no claim cites.
    uncited_evidence_ids: list[str] = Field(default_factory=list)


def build_provenance(decision: Decision) -> DecisionProvenance:
    by_id = {e.evidence_id: e for e in decision.evidence}
    cited: set[str] = set()
    claims: list[ProvenanceClaim] = []

    for claim in decision.claims:
        resolved: list[ProvenanceEvidence] = []
        unresolved: list[str] = []
        for evidence_id in claim.supporting_evidence:
            evidence = by_id.get(evidence_id)
            if evidence is None:
                unresolved.append(evidence_id)
                continue
            cited.add(evidence_id)
            resolved.append(
                ProvenanceEvidence(
                    evidence_id=evidence.evidence_id,
                    statement=evidence.statement,
                    source=evidence.source,
                    relevance=evidence.relevance,
                )
            )
        claims.append(
            ProvenanceClaim(
                statement=claim.statement,
                evidence=resolved,
                unresolved_evidence_ids=unresolved,
            )
        )

    return DecisionProvenance(
        decision_id=decision.decision_id,
        workspace_id=decision.workspace_id,
        question=decision.question,
        recommendation=ProvenanceRecommendation(
            statement=decision.recommendation.statement,
            rationale=decision.recommendation.rationale,
            confidence=decision.recommendation.confidence,
            claims=claims,
        ),
        sources=list(decision.sources),
        uncited_evidence_ids=[
            e.evidence_id for e in decision.evidence if e.evidence_id not in cited
        ],
    )
