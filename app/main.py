from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.models import (
    ChatRequest,
    ChatResponse,
    DecisionRequest,
    IngestRequest,
    IngestResponse,
    ReassessmentRequest,
    RetrievalMetadata,
    WorkspaceRequest,
    WorkspaceResponse,
)
from app.config import get_settings
from app.container import AppContainer, build_container
from app.decisions.analyst import DecisionAnalysisError
from app.decisions.comparison import DecisionComparison, compare_decisions
from app.decisions.models import Decision
from app.decisions.provenance import DecisionProvenance, build_provenance
from app.decisions.validation import ValidationResult, validate_decision
from app.domain import LLMRateLimitError, SourceDocument


class UTF8JSONResponse(JSONResponse):
    """JSON responses that declare their encoding.

    Starlette already emits UTF-8 bytes but labels them `application/json`
    with no charset, so clients that fall back to latin-1 (Windows PowerShell
    5.1's Invoke-RestMethod among them) render en dashes and curly quotes as
    mojibake. Naming the charset fixes it at the boundary that omitted it.
    """

    media_type = "application/json; charset=utf-8"


def _rate_limited(exc: LLMRateLimitError) -> HTTPException:
    headers = {"Retry-After": exc.retry_after} if exc.retry_after else None
    return HTTPException(status_code=429, detail=str(exc), headers=headers)


def create_app(container: AppContainer | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or build_container(get_settings())
        yield

    app = FastAPI(
        title="Evidence-Driven Decision Intelligence Platform",
        version="0.2.0",
        lifespan=lifespan,
        default_response_class=UTF8JSONResponse,
    )

    def _workspace(request: Request, workspace_id: str):
        try:
            return request.app.state.container.workspaces.get(workspace_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def _decision(request: Request, workspace_id: str, decision_id: str):
        """Load a decision or 404. A decision owned by another workspace is
        indistinguishable from one that does not exist."""
        workspace = _workspace(request, workspace_id)
        decision = await request.app.state.container.knowledge.get_decision(
            workspace.workspace_id, decision_id
        )
        if decision is None:
            raise HTTPException(
                status_code=404,
                detail=f"decision '{decision_id}' does not exist in this workspace",
            )
        return workspace, decision

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
                build_graph=payload.build_graph,
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
            graph_built=result.graph_built,
        )

    @app.post("/workspaces/{workspace_id}/graph", status_code=202)
    async def build_graph(workspace_id: str, request: Request) -> dict[str, str]:
        """Run LLM graph enrichment over everything already ingested.

        Separate from ingest because it is the metered, slow half of Cognee's
        pipeline; ingestion stays fast and semantic retrieval works without it.
        """
        workspace = _workspace(request, workspace_id)
        try:
            await request.app.state.container.knowledge.build_graph(
                workspace.workspace_id
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail="Graph enrichment did not finish within COGNEE_TIMEOUT_SECONDS.",
            ) from exc
        return {"workspace_id": workspace.workspace_id, "status": "graph_built"}

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
        except LLMRateLimitError as exc:
            raise _rate_limited(exc) from exc
        return ChatResponse(
            answer=result.answer,
            sources=list(result.sources),
            retrieval=RetrievalMetadata(
                semantic_hits=result.semantic_hits,
                graph_hits=result.graph_hits,
                memory_hits=result.memory_hits,
            ),
        )

    @app.post(
        "/workspaces/{workspace_id}/decisions",
        response_model=Decision,
        status_code=201,
    )
    async def analyze_decision(
        workspace_id: str, payload: DecisionRequest, request: Request
    ) -> Decision:
        workspace = _workspace(request, workspace_id)
        try:
            return await request.app.state.container.decision_agent.run(
                payload.question, workspace.workspace_id, payload.session_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LLMRateLimitError as exc:
            raise _rate_limited(exc) from exc
        except DecisionAnalysisError as exc:
            # A failed LLM stage must surface, never yield a fabricated decision.
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(
                status_code=504, detail="Decision analysis timed out"
            ) from exc

    @app.get("/workspaces/{workspace_id}/decisions", response_model=list[Decision])
    async def list_decisions(
        workspace_id: str, request: Request, limit: int = 10
    ) -> list[Decision]:
        workspace = _workspace(request, workspace_id)
        return await request.app.state.container.knowledge.load_decisions(
            workspace.workspace_id, limit=limit
        )

    @app.get(
        "/workspaces/{workspace_id}/decisions/{decision_id}", response_model=Decision
    )
    async def get_decision(
        workspace_id: str, decision_id: str, request: Request
    ) -> Decision:
        _, decision = await _decision(request, workspace_id, decision_id)
        return decision

    @app.post(
        "/workspaces/{workspace_id}/decisions/{decision_id}/reassess",
        response_model=Decision,
        status_code=201,
    )
    async def reassess_decision(
        workspace_id: str,
        decision_id: str,
        payload: ReassessmentRequest,
        request: Request,
    ) -> Decision:
        """Revisit one decision. The route stays thin: it resolves the target
        and hands it to the existing DecisionAgent, which owns the workflow."""
        workspace, previous = await _decision(request, workspace_id, decision_id)
        try:
            return await request.app.state.container.decision_agent.run(
                payload.question,
                workspace.workspace_id,
                payload.session_id,
                reassess_decision_id=previous.decision_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LLMRateLimitError as exc:
            raise _rate_limited(exc) from exc
        except DecisionAnalysisError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(
                status_code=504, detail="Decision analysis timed out"
            ) from exc

    @app.get(
        "/workspaces/{workspace_id}/decisions/{decision_id}/compare/{other_decision_id}",
        response_model=DecisionComparison,
    )
    async def compare(
        workspace_id: str, decision_id: str, other_decision_id: str, request: Request
    ) -> DecisionComparison:
        _, left = await _decision(request, workspace_id, decision_id)
        _, right = await _decision(request, workspace_id, other_decision_id)
        return compare_decisions(left, right)

    @app.get(
        "/workspaces/{workspace_id}/decisions/{decision_id}/provenance",
        response_model=DecisionProvenance,
    )
    async def provenance(
        workspace_id: str, decision_id: str, request: Request
    ) -> DecisionProvenance:
        _, decision = await _decision(request, workspace_id, decision_id)
        return build_provenance(decision)

    @app.get(
        "/workspaces/{workspace_id}/decisions/{decision_id}/validation",
        response_model=ValidationResult,
    )
    async def validation(
        workspace_id: str, decision_id: str, request: Request
    ) -> ValidationResult:
        workspace, decision = await _decision(request, workspace_id, decision_id)
        known = await request.app.state.container.knowledge.known_decision_ids(
            workspace.workspace_id
        )
        return validate_decision(decision, known_decision_ids=known)

    return app


app = create_app()
