from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class InlineDocument(BaseModel):
    content: str = Field(min_length=1)
    file_name: str = Field(min_length=1)
    document_type: str = "text"
    source: str = "manual"
    location: str | None = None
    timestamp: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    workspace_id: str | None = None


class IngestedDocumentResponse(BaseModel):
    file_name: str
    source: str
    document_type: str
    location: str | None = None
    ingested_at: datetime


class WorkspaceResponse(BaseModel):
    workspace_id: str
    name: str
    description: str
    created_at: datetime
    documents: list[IngestedDocumentResponse] = Field(default_factory=list)
    document_count: int = 0
    graph_built: bool = False
    knowledge_updated_at: datetime | None = None

    @classmethod
    def of(cls, workspace) -> WorkspaceResponse:
        data = workspace.to_dict()
        return cls(**data, document_count=len(data["documents"]))


class IngestRequest(BaseModel):
    documents: list[InlineDocument] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    github_repository: str | None = None
    # LLM graph enrichment: slow and metered. None uses the server default.
    build_graph: bool | None = None


class IngestResponse(BaseModel):
    workspace_id: str
    documents_ingested: int
    dataset: str
    graph_built: bool = False


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = "default"


class RetrievalMetadata(BaseModel):
    semantic_hits: int
    graph_hits: int
    memory_hits: int


class DecisionRequest(BaseModel):
    question: str = Field(min_length=1)
    session_id: str = "default"


class ReassessmentRequest(BaseModel):
    session_id: str = "default"
    question: str = Field(
        default="Reassess this decision using current workspace knowledge.",
        min_length=1,
    )


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    retrieval: RetrievalMetadata
