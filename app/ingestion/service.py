from __future__ import annotations

from pathlib import Path

from app.domain import IngestResult, KnowledgeService, SourceDocument
from app.ingestion.files import load_directory, load_file
from app.ingestion.github import GitHubLoader


class IngestionService:
    """Source-agnostic ingestion into a workspace's knowledge layer."""

    def __init__(
        self, knowledge: KnowledgeService, github_loader: GitHubLoader
    ) -> None:
        self._knowledge = knowledge
        self._github_loader = github_loader

    async def ingest(
        self,
        workspace_id: str,
        *,
        paths: list[Path] | None = None,
        documents: list[SourceDocument] | None = None,
        github_repository: str | None = None,
        build_graph: bool | None = None,
    ) -> IngestResult:
        collected = list(documents or [])
        for path in paths or []:
            path = Path(path)
            if path.is_dir():
                collected.extend(load_directory(path))
            else:
                collected.append(load_file(path))
        if github_repository:
            collected.extend(await self._github_loader.load(github_repository))
        if not collected:
            raise ValueError(
                "Provide at least one path, inline document, or GitHub repository"
            )
        return await self._knowledge.ingest(
            workspace_id, collected, build_graph=build_graph
        )
