"""Structured decision persistence.

Same approach as WorkspaceRegistry: one JSON file under the app data
directory. No new database, and — unlike Cognee's semantic memory — it
round-trips a Decision losslessly, which reassessment depends on.
Decisions are also written into Cognee memory (see CogneeKnowledgeService)
so they participate in semantic and graph retrieval.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from pydantic import ValidationError

from app.decisions.models import Decision
from app.workspaces.service import write_json_atomically

logger = logging.getLogger(__name__)


class DecisionStore:
    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path
        self._lock = threading.Lock()

    def _read_all(self) -> list[dict]:
        if not self._store_path.exists():
            return []
        try:
            records = json.loads(self._store_path.read_text(encoding="utf-8") or "[]")
        except json.JSONDecodeError:
            logger.error("decision store at %s is not valid JSON", self._store_path)
            return []
        return records if isinstance(records, list) else []

    def _decisions_for(self, workspace_id: str) -> list[Decision]:
        """Parse a workspace's decisions, skipping records that no longer fit
        the schema rather than failing every read because of one bad row."""
        decisions: list[Decision] = []
        for record in self._read_all():
            if not isinstance(record, dict):
                continue
            if record.get("workspace_id") != workspace_id:
                continue
            try:
                decisions.append(Decision.model_validate(record))
            except ValidationError:
                logger.warning(
                    "skipping malformed decision record %r in workspace %s",
                    record.get("decision_id"),
                    workspace_id,
                )
        decisions.sort(key=lambda d: d.created_at, reverse=True)
        return decisions

    def append(self, decision: Decision) -> None:
        with self._lock:
            records = self._read_all()
            records.append(json.loads(decision.model_dump_json()))
            # Atomic: a crash mid-write leaves the previous file intact.
            write_json_atomically(self._store_path, records)

    def list_for_workspace(self, workspace_id: str, limit: int = 10) -> list[Decision]:
        """Most recent first, scoped to one workspace."""
        return self._decisions_for(workspace_id)[:limit]

    def get(self, workspace_id: str, decision_id: str) -> Decision | None:
        """One decision, or None when it is absent *or* owned by another
        workspace — the caller cannot tell the two apart, which is the point."""
        for decision in self._decisions_for(workspace_id):
            if decision.decision_id == decision_id:
                return decision
        return None

    def known_ids(self, workspace_id: str) -> set[str]:
        return {d.decision_id for d in self._decisions_for(workspace_id)}
