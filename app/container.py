from __future__ import annotations

from dataclasses import dataclass

from app.agent.generator import AnswerGenerator
from app.agent.graph import WorkspaceAgent
from app.config import Settings
from app.domain import KnowledgeService
from app.ingestion.github import GitHubLoader
from app.ingestion.service import IngestionService
from app.retrieval import WorkspaceRetriever
from app.workspaces import WorkspaceRegistry


@dataclass(frozen=True, slots=True)
class AppContainer:
    """Explicit wiring so tests can substitute the knowledge layer and LLM."""

    settings: Settings
    knowledge: KnowledgeService
    workspaces: WorkspaceRegistry
    ingestion: IngestionService
    retriever: WorkspaceRetriever
    agent: WorkspaceAgent


def build_container(
    settings: Settings,
    *,
    knowledge: KnowledgeService | None = None,
    generator: AnswerGenerator | None = None,
) -> AppContainer:
    if knowledge is None:
        from app.knowledge.cognee_service import CogneeKnowledgeService

        knowledge = CogneeKnowledgeService(settings)
    generator = generator or AnswerGenerator(settings)
    retriever = WorkspaceRetriever(knowledge)
    return AppContainer(
        settings=settings,
        knowledge=knowledge,
        workspaces=WorkspaceRegistry(settings.workspace_store_path),
        ingestion=IngestionService(knowledge, GitHubLoader(settings)),
        retriever=retriever,
        agent=WorkspaceAgent(retriever, knowledge, generator),
    )
