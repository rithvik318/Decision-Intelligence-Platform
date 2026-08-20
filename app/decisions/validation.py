"""Deterministic structural validation of a stored decision.

This is a schema-and-provenance checker, not an LLM judge: it asks whether a
decision is internally well-formed and traceable, never whether it is a good
decision. Errors mark structural or provenance violations; warnings mark
quality concerns that leave the object usable.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.decisions.models import Decision, DecisionStatus

# Evidence ids are assigned as E1, E2, ... by the analysis stage.
EVIDENCE_REFERENCE = re.compile(r"\bE\d+\b")


class ValidationIssue(BaseModel):
    code: str
    message: str
    subject: str | None = None


class ValidationResult(BaseModel):
    decision_id: str
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)


def validate_decision(
    decision: Decision, known_decision_ids: set[str] | None = None
) -> ValidationResult:
    """Check one decision. `known_decision_ids` scopes the `supersedes` check
    to the same workspace, so a dangling link is caught rather than assumed."""
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    evidence_ids: set[str] = set()
    for evidence in decision.evidence:
        if not evidence.evidence_id.strip():
            errors.append(
                ValidationIssue(
                    code="EVIDENCE_MISSING_ID",
                    message="An evidence item has no evidence_id.",
                    subject=evidence.statement[:120],
                )
            )
            continue
        if evidence.evidence_id in evidence_ids:
            errors.append(
                ValidationIssue(
                    code="EVIDENCE_DUPLICATE_ID",
                    message=f"Evidence id {evidence.evidence_id} is used more than once.",
                    subject=evidence.evidence_id,
                )
            )
        evidence_ids.add(evidence.evidence_id)
        if not evidence.statement.strip():
            errors.append(
                ValidationIssue(
                    code="EVIDENCE_MISSING_STATEMENT",
                    message=f"Evidence {evidence.evidence_id} has no statement.",
                    subject=evidence.evidence_id,
                )
            )
        if not (evidence.source or "").strip():
            warnings.append(
                ValidationIssue(
                    code="EVIDENCE_MISSING_SOURCE",
                    message=(
                        f"Evidence {evidence.evidence_id} has no source, so it "
                        "cannot be traced back to a document."
                    ),
                    subject=evidence.evidence_id,
                )
            )

    # D. A recommendation must be present and say something.
    if not decision.recommendation.statement.strip():
        errors.append(
            ValidationIssue(
                code="RECOMMENDATION_MISSING",
                message="The decision has no recommendation statement.",
            )
        )
    if not decision.recommendation.rationale.strip():
        warnings.append(
            ValidationIssue(
                code="RECOMMENDATION_MISSING_RATIONALE",
                message="The recommendation has no rationale.",
            )
        )

    # A, B. Claims must cite evidence, and the evidence must exist.
    if not decision.claims:
        warnings.append(
            ValidationIssue(
                code="NO_CLAIMS",
                message="The decision derives no claims from its evidence.",
            )
        )
    for claim in decision.claims:
        if not claim.supporting_evidence:
            errors.append(
                ValidationIssue(
                    code="CLAIM_MISSING_EVIDENCE",
                    message="A claim cites no supporting evidence.",
                    subject=claim.statement[:120],
                )
            )
            continue
        for evidence_id in claim.supporting_evidence:
            if evidence_id not in evidence_ids:
                errors.append(
                    ValidationIssue(
                        code="CLAIM_UNKNOWN_EVIDENCE",
                        message=(
                            f"A claim cites evidence {evidence_id}, which this "
                            "decision does not contain."
                        ),
                        subject=claim.statement[:120],
                    )
                )

    # E, F. Alternatives should exist, and their evidence references resolve.
    if not decision.alternatives:
        warnings.append(
            ValidationIssue(
                code="NO_ALTERNATIVES",
                message="No alternatives were weighed.",
            )
        )
    for alternative in decision.alternatives:
        for evidence_id in alternative.evidence:
            if evidence_id not in evidence_ids:
                errors.append(
                    ValidationIssue(
                        code="ALTERNATIVE_UNKNOWN_EVIDENCE",
                        message=(
                            f"Alternative '{alternative.name}' cites evidence "
                            f"{evidence_id}, which this decision does not contain."
                        ),
                        subject=alternative.name,
                    )
                )
        if not alternative.advantages and not alternative.disadvantages:
            warnings.append(
                ValidationIssue(
                    code="ALTERNATIVE_NOT_WEIGHED",
                    message=(
                        f"Alternative '{alternative.name}' lists neither "
                        "advantages nor disadvantages."
                    ),
                    subject=alternative.name,
                )
            )

    # G. Free-text rationales must not point at evidence that is not there.
    for risk in decision.risks:
        for evidence_id in EVIDENCE_REFERENCE.findall(risk.rationale):
            if evidence_id not in evidence_ids:
                errors.append(
                    ValidationIssue(
                        code="RISK_UNKNOWN_EVIDENCE",
                        message=(
                            f"A risk rationale references evidence {evidence_id}, "
                            "which this decision does not contain."
                        ),
                        subject=risk.statement[:120],
                    )
                )

    # H, I. Reassessment bookkeeping must be self-consistent.
    reassessed = decision.status is DecisionStatus.REASSESSED
    if decision.changed_since_previous and not reassessed:
        errors.append(
            ValidationIssue(
                code="CHANGED_WITHOUT_REASSESSMENT",
                message=(
                    "changed_since_previous is populated but the decision is not "
                    "marked as a reassessment."
                ),
            )
        )
    if decision.supersedes:
        if not reassessed:
            errors.append(
                ValidationIssue(
                    code="SUPERSEDES_WITHOUT_REASSESSMENT",
                    message=(
                        "supersedes is set but the decision is not marked as a "
                        "reassessment."
                    ),
                    subject=decision.supersedes,
                )
            )
        if known_decision_ids is not None and decision.supersedes not in known_decision_ids:
            errors.append(
                ValidationIssue(
                    code="SUPERSEDES_UNKNOWN_DECISION",
                    message=(
                        f"supersedes points at {decision.supersedes}, which is not "
                        "a decision in this workspace."
                    ),
                    subject=decision.supersedes,
                )
            )
    elif reassessed:
        warnings.append(
            ValidationIssue(
                code="REASSESSMENT_WITHOUT_SUPERSEDES",
                message="The decision is a reassessment but supersedes nothing.",
            )
        )

    return ValidationResult(
        decision_id=decision.decision_id,
        valid=not errors,
        errors=errors,
        warnings=warnings,
    )
