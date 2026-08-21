"""Is a decision still current?

Deterministic and free: compare when a decision was made against when the
workspace's knowledge last changed. No LLM call, no retrieval — the whole
point is that a user can see staleness without paying to ask.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.decisions.models import Decision
from app.domain import Workspace


class DecisionFreshness(BaseModel):
    decision_id: str
    workspace_id: str
    decided_at: datetime
    knowledge_updated_at: datetime | None = None
    stale: bool = False
    # Documents ingested after the decision was made.
    documents_added_since: list[str] = Field(default_factory=list)
    summary: str


def assess_freshness(decision: Decision, workspace: Workspace) -> DecisionFreshness:
    added = sorted(
        {
            document.file_name
            for document in workspace.documents
            if document.ingested_at > decision.created_at
        }
    )
    stale = bool(added) or (
        workspace.knowledge_updated_at is not None
        and workspace.knowledge_updated_at > decision.created_at
    )

    if not workspace.documents:
        summary = "This workspace has no recorded documents, so freshness is unknown."
    elif not stale:
        summary = "No knowledge has been ingested since this decision was made."
    elif added:
        count = len(added)
        phrase = "document was" if count == 1 else "documents were"
        summary = (
            f"{count} {phrase} ingested after this decision was made. "
            "Reassess it to take the new evidence into account."
        )
    else:
        summary = (
            "Workspace knowledge changed after this decision was made. "
            "Reassess it to take the new evidence into account."
        )

    return DecisionFreshness(
        decision_id=decision.decision_id,
        workspace_id=decision.workspace_id,
        decided_at=decision.created_at,
        knowledge_updated_at=workspace.knowledge_updated_at,
        stale=stale,
        documents_added_since=added,
        summary=summary,
    )


class WorkspaceFreshness(BaseModel):
    """Freshness of a whole workspace: which of its decisions new knowledge
    has outrun. Aggregates `assess_freshness` — same rule, one call."""

    workspace_id: str
    knowledge_updated_at: datetime | None = None
    document_count: int = 0
    decision_count: int = 0
    stale_decision_count: int = 0
    stale_decisions: list[DecisionFreshness] = Field(default_factory=list)
    summary: str


def assess_workspace_freshness(
    workspace: Workspace, decisions: list[Decision]
) -> WorkspaceFreshness:
    assessments = [assess_freshness(decision, workspace) for decision in decisions]
    stale = [a for a in assessments if a.stale]

    if not workspace.documents:
        summary = "This workspace has no recorded documents, so freshness is unknown."
    elif not decisions:
        summary = "No decisions have been recorded in this workspace yet."
    elif not stale:
        summary = (
            "No knowledge has been ingested since this decision was made."
            if len(decisions) == 1
            else "No knowledge has been ingested since these decisions were made."
        )
    else:
        count, total = len(stale), len(decisions)
        # The noun agrees with the total, the verb with the stale count:
        # "1 of 2 decisions was made...", "2 of 2 decisions were made...".
        summary = (
            f"{count} of {total} {'decision' if total == 1 else 'decisions'} "
            f"{'was' if count == 1 else 'were'} made before knowledge that has "
            "since been ingested. Reassess to take the new evidence into account."
        )

    return WorkspaceFreshness(
        workspace_id=workspace.workspace_id,
        knowledge_updated_at=workspace.knowledge_updated_at,
        document_count=len(workspace.documents),
        decision_count=len(decisions),
        stale_decision_count=len(stale),
        stale_decisions=stale,
        summary=summary,
    )
