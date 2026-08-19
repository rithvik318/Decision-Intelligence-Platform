"""Workspace registry.

V1 persistence is a single JSON file under the app data directory. This keeps
the Workspace concept explicit without introducing a relational database; the
knowledge itself already lives in Cognee.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from app.domain import Workspace


def normalize_workspace_id(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    if not slug:
        raise ValueError("workspace id must contain at least one letter or number")
    return slug


class WorkspaceRegistry:
    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path
        self._lock = threading.Lock()
        self._workspaces: dict[str, Workspace] = {}
        self._load()

    def _load(self) -> None:
        if not self._store_path.exists():
            return
        raw = json.loads(self._store_path.read_text(encoding="utf-8") or "[]")
        self._workspaces = {
            item["workspace_id"]: Workspace.from_dict(item) for item in raw
        }

    def _flush(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [w.to_dict() for w in self._workspaces.values()]
        self._store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def create(
        self, name: str, description: str = "", workspace_id: str | None = None
    ) -> Workspace:
        slug = normalize_workspace_id(workspace_id or name)
        with self._lock:
            if slug in self._workspaces:
                raise ValueError(f"workspace '{slug}' already exists")
            workspace = Workspace(
                workspace_id=slug, name=name.strip(), description=description.strip()
            )
            self._workspaces[slug] = workspace
            self._flush()
        return workspace

    def get(self, workspace_id: str) -> Workspace:
        slug = normalize_workspace_id(workspace_id)
        workspace = self._workspaces.get(slug)
        if workspace is None:
            raise KeyError(f"workspace '{slug}' does not exist")
        return workspace

    def ensure(self, workspace_id: str, name: str | None = None) -> Workspace:
        try:
            return self.get(workspace_id)
        except KeyError:
            return self.create(name or workspace_id, workspace_id=workspace_id)

    def list(self) -> list[Workspace]:
        return sorted(self._workspaces.values(), key=lambda w: w.created_at)
