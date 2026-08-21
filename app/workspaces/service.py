"""Workspace registry.

V1 persistence is a single JSON file under the app data directory. No new
database, and — as with the decision store — writes land atomically so a crash
mid-write cannot truncate the file.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path

from app.domain import IngestedDocument, SourceDocument, Workspace, utcnow

logger = logging.getLogger(__name__)


def normalize_workspace_id(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    if not slug:
        raise ValueError("workspace id must contain at least one letter or number")
    return slug


def write_json_atomically(path: Path, payload: object) -> None:
    """Write via a sibling temp file and one rename.

    `os.replace` is atomic on POSIX and Windows, so a reader either sees the
    old file or the new one — never a half-written array.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


class WorkspaceRegistry:
    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path
        self._lock = threading.Lock()
        self._workspaces: dict[str, Workspace] = {}
        self._load()

    def _load(self) -> None:
        if not self._store_path.exists():
            return
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8") or "[]")
        except json.JSONDecodeError:
            logger.error("workspace store at %s is not valid JSON", self._store_path)
            return
        for item in raw if isinstance(raw, list) else []:
            try:
                workspace = Workspace.from_dict(item)
            except (KeyError, TypeError, ValueError):
                logger.warning("skipping malformed workspace record %r", item)
                continue
            self._workspaces[workspace.workspace_id] = workspace

    def _flush(self) -> None:
        write_json_atomically(
            self._store_path, [w.to_dict() for w in self._workspaces.values()]
        )

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

    def record_ingestion(
        self,
        workspace_id: str,
        documents: list[SourceDocument],
        *,
        graph_built: bool = False,
    ) -> Workspace:
        """Note what was ingested and when.

        `knowledge_updated_at` is what makes decision staleness computable
        without asking the LLM anything.
        """
        with self._lock:
            existing = self.get(workspace_id)
            ingested_at = utcnow()
            added = tuple(
                IngestedDocument(
                    file_name=document.file_name,
                    source=document.source,
                    document_type=document.document_type,
                    location=document.location,
                    ingested_at=ingested_at,
                )
                for document in documents
            )
            # Re-ingesting a file replaces its earlier record rather than
            # listing the same document twice.
            replaced = {d.file_name for d in added}
            kept = tuple(d for d in existing.documents if d.file_name not in replaced)
            updated = Workspace(
                workspace_id=existing.workspace_id,
                name=existing.name,
                description=existing.description,
                created_at=existing.created_at,
                documents=kept + added,
                graph_built=existing.graph_built or graph_built,
                knowledge_updated_at=ingested_at,
            )
            self._workspaces[updated.workspace_id] = updated
            self._flush()
        return updated

    def record_graph_built(self, workspace_id: str) -> Workspace:
        with self._lock:
            existing = self.get(workspace_id)
            updated = Workspace(
                workspace_id=existing.workspace_id,
                name=existing.name,
                description=existing.description,
                created_at=existing.created_at,
                documents=existing.documents,
                graph_built=True,
                knowledge_updated_at=existing.knowledge_updated_at,
            )
            self._workspaces[updated.workspace_id] = updated
            self._flush()
        return updated
