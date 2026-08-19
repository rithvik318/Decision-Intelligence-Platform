from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from app.api.models import (
    ChatRequest,
    ChatResponse,
    IngestRequest,
    IngestResponse,
    RetrievalMetadata,
    WorkspaceRequest,
    WorkspaceResponse,
)
from app.config import get_settings
from app.container import AppContainer, build_container
from app.domain import SourceDocument


def create_app(container: AppContainer | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or build_container(get_settings())
        yield

    app = FastAPI(
        title="Evidence-Driven Decision Intelligence Platform",
        version="0.2.0",
        lifespan=lifespan,
    )

    def _workspace(request: Request, workspace_id: str):
        try:
            return request.app.state.container.workspaces.get(workspace_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/workspaces", response_model=WorkspaceResponse, status_code=201)
    async def create_workspace(
        payload: WorkspaceRequest, request: Request
    ) -> WorkspaceResponse:
        try:
            workspace = request.app.state.container.workspaces.create(
                payload.name, payload.description, payload.workspace_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return WorkspaceResponse(**workspace.to_dict())

    @app.get("/workspaces", response_model=list[WorkspaceResponse])
    async def list_workspaces(request: Request) -> list[WorkspaceResponse]:
        return [
            WorkspaceResponse(**w.to_dict())
            for w in request.app.state.container.workspaces.list()
        ]

    @app.post(
        "/workspaces/{workspace_id}/ingest",
        response_model=IngestResponse,
        status_code=201,
    )
    async def ingest(
        workspace_id: str, payload: IngestRequest, request: Request
    ) -> IngestResponse:
        workspace = _workspace(request, workspace_id)
        documents = [SourceDocument(**item.model_dump()) for item in payload.documents]
        try:
            result = await request.app.state.container.ingestion.ingest(
                workspace.workspace_id,
                documents=documents,
                paths=[Path(p) for p in payload.paths],
                github_repository=payload.github_repository,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail=(
                    "Cognee did not return within COGNEE_TIMEOUT_SECONDS. The "
                    "pipeline may have completed; check the server log."
                ),
            ) from exc
        return IngestResponse(
            workspace_id=result.workspace_id,
            documents_ingested=result.documents_ingested,
            dataset=result.dataset,
        )

    @app.post("/workspaces/{workspace_id}/chat", response_model=ChatResponse)
    async def chat(
        workspace_id: str, payload: ChatRequest, request: Request
    ) -> ChatResponse:
        workspace = _workspace(request, workspace_id)
        try:
            result = await request.app.state.container.agent.run(
                payload.message, workspace.workspace_id, payload.session_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ChatResponse(
            answer=result.answer,
            sources=list(result.sources),
            retrieval=RetrievalMetadata(
                semantic_hits=result.semantic_hits,
                graph_hits=result.graph_hits,
                memory_hits=result.memory_hits,
            ),
        )

    return app


app = create_app()
