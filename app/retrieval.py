from __future__ import annotations

import asyncio

from app.domain import KnowledgeService, RetrievalContext


class WorkspaceRetriever:
    """Coordinate Cognee semantic, graph, and session-memory retrieval for a workspace."""

    def __init__(self, knowledge: KnowledgeService) -> None:
        self._knowledge = knowledge

    async def retrieve_context(
        self, workspace_id: str, session_id: str, query: str
    ) -> RetrievalContext:
        semantic, graph, memories = await asyncio.gather(
            self._knowledge.semantic_search(workspace_id, query),
            self._knowledge.graph_search(workspace_id, query),
            self._knowledge.recall(workspace_id, session_id, query),
        )
        return RetrievalContext(
            query=query,
            workspace_id=workspace_id,
            semantic=tuple(semantic),
            graph=tuple(graph),
            memories=tuple(memories),
        )
