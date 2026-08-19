"""Structured decision persistence.

Same approach as WorkspaceRegistry: one JSON file under the app data
directory. No new database, and — unlike Cognee's semantic memory — it
round-trips a Decision losslessly, which reassessment depends on.
Decisions are also written into Cognee memory (see CogneeKnowledgeService)
so they participate in semantic and graph retrieval.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from app.decisions.models import Decision


class DecisionStore:
    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path
        self._lock = threading.Lock()

    def _read_all(self) -> list[dict]:
        if not self._store_path.exists():
            return []
        return json.loads(self._store_path.read_text(encoding="utf-8") or "[]")

    def append(self, decision: Decision) -> None:
        with self._lock:
            records = self._read_all()
            records.append(json.loads(decision.model_dump_json()))
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            self._store_path.write_text(
                json.dumps(records, indent=2), encoding="utf-8"
            )

    def list_for_workspace(self, workspace_id: str, limit: int = 10) -> list[Decision]:
        """Most recent first, scoped to one workspace."""
        decisions = [
            Decision.model_validate(record)
            for record in self._read_all()
            if record.get("workspace_id") == workspace_id
        ]
        decisions.sort(key=lambda d: d.created_at, reverse=True)
        return decisions[:limit]
