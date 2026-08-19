from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.models import InlineDocument
from app.main import create_app
from tests.fakes import InMemoryKnowledgeFake


def test_workspace_ingest_retrieve_memory_langgraph_and_chat(
    container, fake_knowledge: InMemoryKnowledgeFake, solar_documents
) -> None:
    app = create_app(container)
    payload = {
        "documents": [
            InlineDocument(
                content=document.content,
                file_name=document.file_name,
                document_type=document.document_type,
                source=document.source,
                location=document.location,
            ).model_dump(mode="json")
            for document in solar_documents
        ]
    }

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}

        created = client.post(
            "/workspaces",
            json={
                "name": "Solar Market Analysis",
                "description": "Should we enter the German solar market?",
            },
        )
        assert created.status_code == 201
        workspace_id = created.json()["workspace_id"]
        assert workspace_id == "solar-market-analysis"
        assert created.json()["created_at"]

        listed = client.get("/workspaces").json()
        assert [w["workspace_id"] for w in listed] == [workspace_id]

        ingest = client.post(f"/workspaces/{workspace_id}/ingest", json=payload)
        assert ingest.status_code == 201
        assert ingest.json()["documents_ingested"] == 2
        assert ingest.json()["dataset"] == "workspace-solar-market-analysis"

        chat = client.post(
            f"/workspaces/{workspace_id}/chat",
            json={
                "message": "Which competitors depend on suppliers in the German market?",
                "session_id": "review-1",
            },
        )

    assert chat.status_code == 200
    body = chat.json()
    assert "Nordlicht" in body["answer"]
    assert set(body["sources"]) >= {"competitors.txt"}
    assert body["retrieval"]["semantic_hits"] >= 1
    assert body["retrieval"]["graph_hits"] >= 1
    # LangGraph's final node persisted the interaction into the memory layer.
    assert fake_knowledge.memories[(workspace_id, "review-1")]


def test_unknown_workspace_is_rejected(container) -> None:
    app = create_app(container)
    with TestClient(app) as client:
        assert (
            client.post(
                "/workspaces/missing/chat", json={"message": "hello"}
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/workspaces/missing/ingest", json={"documents": []}
            ).status_code
            == 404
        )


def test_ingest_is_llm_free_by_default_and_graph_is_opt_in(
    container, fake_knowledge
) -> None:
    """Graph enrichment is the metered half of Cognee's pipeline: opt-in."""
    app = create_app(container)
    document = {"content": "Grid capacity is constrained.", "file_name": "a.md"}

    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Solar"})

        default = client.post("/workspaces/solar/ingest", json={"documents": [document]})
        assert default.json()["graph_built"] is False
        assert fake_knowledge.graphs_built == []

        opted_in = client.post(
            "/workspaces/solar/ingest",
            json={"documents": [document], "build_graph": True},
        )
        assert opted_in.json()["graph_built"] is True
        assert fake_knowledge.graphs_built == ["solar"]

        # and it can be run later over already-ingested data
        later = client.post("/workspaces/solar/graph")
        assert later.status_code == 202
        assert later.json()["status"] == "graph_built"
        assert fake_knowledge.graphs_built == ["solar", "solar"]
