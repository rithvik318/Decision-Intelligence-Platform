"""Core domain types and service boundaries.

Everything the application layer needs to talk about documents, retrieval and
knowledge lives here so that concrete infrastructure (Cognee, OpenAI, FastAPI)
can be swapped or faked without touching business logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

DocumentType = str


class LLMRateLimitError(RuntimeError):
    """The LLM provider returned 429. Carries Retry-After when the provider sent one."""

    def __init__(self, message: str, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class IngestedDocument:
    """What a workspace knows it holds. Recorded at ingest so the corpus can be
    listed and so a decision can be dated against the knowledge behind it."""

    file_name: str
    source: str = "manual"
    document_type: str = "text"
    location: str | None = None
    ingested_at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "source": self.source,
            "document_type": self.document_type,
            "location": self.location,
            "ingested_at": self.ingested_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IngestedDocument:
        return cls(
            file_name=data["file_name"],
            source=data.get("source", "manual"),
            document_type=data.get("document_type", "text"),
            location=data.get("location"),
            ingested_at=datetime.fromisoformat(data["ingested_at"]),
        )


@dataclass(frozen=True, slots=True)
class Workspace:
    """An information/decision domain, plus the state a UI needs to describe it."""

    workspace_id: str
    name: str
    description: str = ""
    created_at: datetime = field(default_factory=utcnow)
    documents: tuple[IngestedDocument, ...] = ()
    graph_built: bool = False
    knowledge_updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "documents": [d.to_dict() for d in self.documents],
            "graph_built": self.graph_built,
            "knowledge_updated_at": (
                self.knowledge_updated_at.isoformat()
                if self.knowledge_updated_at
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Workspace:
        updated = data.get("knowledge_updated_at")
        return cls(
            workspace_id=data["workspace_id"],
            name=data["name"],
            description=data.get("description", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            documents=tuple(
                IngestedDocument.from_dict(d) for d in data.get("documents", [])
            ),
            graph_built=bool(data.get("graph_built", False)),
            knowledge_updated_at=datetime.fromisoformat(updated) if updated else None,
        )


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """A normalized unit of ingested text, independent of where it came from."""

    content: str
    file_name: str
    document_type: DocumentType = "text"
    source: str = "manual"
    location: str | None = None  # path or URL where applicable
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_knowledge_text(self) -> str:
        """Embed provenance in the text so it survives into the graph/vector store."""
        header = [
            f"file_name: {self.file_name}",
            f"source: {self.source}",
            f"document_type: {self.document_type}",
        ]
        if self.location:
            header.append(f"location: {self.location}")
        if self.timestamp:
            header.append(f"timestamp: {self.timestamp}")
        for key, value in self.metadata.items():
            header.append(f"{key}: {value}")
        return "\n".join(header) + "\n\n" + self.content


@dataclass(frozen=True, slots=True)
class IngestResult:
    workspace_id: str
    documents_ingested: int
    dataset: str
    graph_built: bool = False
    # What was ingested. Populated by IngestionService, which is the only layer
    # that sees documents loaded from paths or GitHub as well as inline ones.
    documents: tuple[SourceDocument, ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievedItem:
    text: str
    retrieval_type: str  # semantic | graph | memory
    score: float | None = None
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalContext:
    query: str
    workspace_id: str
    semantic: tuple[RetrievedItem, ...] = ()
    graph: tuple[RetrievedItem, ...] = ()
    memories: tuple[RetrievedItem, ...] = ()

    @property
    def items(self) -> tuple[RetrievedItem, ...]:
        return self.semantic + self.graph + self.memories

    def as_prompt_block(self, limit: int = 12) -> str:
        lines: list[str] = []
        for index, item in enumerate(self.items[:limit], start=1):
            label = item.source or item.retrieval_type
            lines.append(f"[{index}] ({item.retrieval_type}, {label}) {item.text}")
        return "\n".join(lines) if lines else "(no context retrieved)"


@runtime_checkable
class KnowledgeService(Protocol):
    """Application-level boundary the future decision agent will code against.

    Cognee is the only production implementation; tests use an in-memory fake.
    """

    async def ingest(
        self,
        workspace_id: str,
        documents: list[SourceDocument],
        *,
        build_graph: bool | None = None,
    ) -> IngestResult: ...

    async def build_graph(self, workspace_id: str) -> None:
        """Run LLM graph enrichment over everything already ingested."""
        ...

    async def semantic_search(
        self, workspace_id: str, query: str, *, limit: int = 6
    ) -> list[RetrievedItem]: ...

    async def graph_search(
        self, workspace_id: str, query: str, *, limit: int = 6
    ) -> list[RetrievedItem]: ...

    async def remember(
        self, workspace_id: str, session_id: str, content: str
    ) -> None: ...

    async def recall(
        self, workspace_id: str, session_id: str, query: str, *, limit: int = 4
    ) -> list[RetrievedItem]: ...

    # Decision memory. Typed as Any to keep app.decisions out of this module's
    # imports; implementations take and return app.decisions.models.Decision.
    async def store_decision(
        self, workspace_id: str, session_id: str, decision: Any
    ) -> None: ...

    async def load_decisions(
        self, workspace_id: str, *, limit: int = 5
    ) -> list[Any]: ...

    async def get_decision(self, workspace_id: str, decision_id: str) -> Any | None:
        """One workspace-scoped decision, or None when absent or not owned."""
        ...

    async def known_decision_ids(self, workspace_id: str) -> set[str]: ...
