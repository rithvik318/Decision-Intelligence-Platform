"""Deterministic in-memory doubles: no network, no API key, no Cognee."""

from __future__ import annotations

from collections import defaultdict

from app.agent.generator import GeneratedAnswer
from app.domain import IngestResult, RetrievalContext, RetrievedItem, SourceDocument


def _tokens(text: str) -> set[str]:
    """Crude stems so the fake behaves a little like semantic search."""
    return {
        t.strip(".,;:()?!\"'").lower()[:6]
        for t in text.split()
        if len(t.strip(".,;:()?!\"'")) > 2
    }


class InMemoryKnowledgeFake:
    """Implements the KnowledgeService protocol with naive token overlap."""

    def __init__(self) -> None:
        self.documents: dict[str, list[SourceDocument]] = defaultdict(list)
        self.memories: dict[tuple[str, str], list[str]] = defaultdict(list)

    @staticmethod
    def _dataset(workspace_id: str) -> str:
        return f"workspace-{workspace_id.lower()}"

    async def ingest(
        self, workspace_id: str, documents: list[SourceDocument]
    ) -> IngestResult:
        if not documents:
            raise ValueError("At least one document is required")
        self.documents[workspace_id].extend(documents)
        return IngestResult(
            workspace_id, len(documents), self._dataset(workspace_id)
        )

    def _match(self, workspace_id: str, query: str) -> list[SourceDocument]:
        query_tokens = _tokens(query)
        scored = [
            (len(query_tokens & _tokens(doc.content)), doc)
            for doc in self.documents.get(workspace_id, [])
        ]
        return [doc for score, doc in sorted(scored, key=lambda p: -p[0]) if score]

    async def semantic_search(
        self, workspace_id: str, query: str, *, limit: int = 6
    ) -> list[RetrievedItem]:
        return [
            RetrievedItem(
                text=doc.content,
                retrieval_type="semantic",
                score=1.0,
                source=doc.file_name,
                metadata={"file_name": doc.file_name, "source": doc.source},
            )
            for doc in self._match(workspace_id, query)[:limit]
        ]

    async def graph_search(
        self, workspace_id: str, query: str, *, limit: int = 6
    ) -> list[RetrievedItem]:
        items: list[RetrievedItem] = []
        for doc in self._match(workspace_id, query)[:limit]:
            for line in doc.content.splitlines():
                if " depends on " in line or " competes with " in line:
                    items.append(
                        RetrievedItem(
                            text=line.strip(),
                            retrieval_type="graph",
                            source=doc.file_name,
                            metadata={"file_name": doc.file_name},
                        )
                    )
        return items[:limit]

    async def remember(
        self, workspace_id: str, session_id: str, content: str
    ) -> None:
        self.memories[(workspace_id, session_id)].append(content)

    async def recall(
        self, workspace_id: str, session_id: str, query: str, *, limit: int = 4
    ) -> list[RetrievedItem]:
        query_tokens = _tokens(query)
        return [
            RetrievedItem(text=memory, retrieval_type="memory", source="memory")
            for memory in self.memories.get((workspace_id, session_id), [])
            if query_tokens & _tokens(memory)
        ][:limit]


class EchoGenerator:
    """Answers by quoting retrieved context, so assertions stay deterministic."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate(
        self, question: str, context: RetrievalContext
    ) -> GeneratedAnswer:
        self.calls.append(question)
        if not context.items:
            return GeneratedAnswer(
                answer="No evidence in this workspace yet.",
                needs_more_information=True,
            )
        quoted = " ".join(
            f"[{index}] {item.text.strip()[:160]}"
            for index, item in enumerate(context.items[:3], start=1)
        )
        return GeneratedAnswer(
            answer=f"Based on workspace evidence: {quoted}",
            needs_more_information=False,
        )
