"""Phase 4: ingestion safety, workspace state, freshness, CORS, atomic writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.decisions.freshness import assess_freshness
from app.decisions.models import Decision, Recommendation
from app.decisions.validation import validate_decision
from app.domain import IngestedDocument, SourceDocument, Workspace
from app.ingestion.paths import UnsafeIngestPath, resolve_within
from app.main import create_app
from app.workspaces.service import WorkspaceRegistry, write_json_atomically
from tests.test_decision_history import make_decision

# --- ingestion path safety --------------------------------------------------


def test_paths_outside_the_root_are_rejected(tmp_path) -> None:
    root = tmp_path / "corpus"
    (root / "sub").mkdir(parents=True)
    inside = root / "sub" / "note.md"
    inside.write_text("hello", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("private", encoding="utf-8")

    assert resolve_within(inside, root) == inside.resolve()
    assert resolve_within(root, root) == root.resolve()

    with pytest.raises(UnsafeIngestPath):
        resolve_within(outside, root)
    # traversal is normalised before the check, not pattern-matched away
    with pytest.raises(UnsafeIngestPath):
        resolve_within(root / "sub" / ".." / ".." / "secret.txt", root)
    with pytest.raises(UnsafeIngestPath):
        resolve_within(Path("/etc/passwd"), root)


def test_ingest_endpoint_rejects_an_unsafe_path(container, settings, tmp_path) -> None:
    outside = tmp_path.parent / "elsewhere.txt"
    outside.write_text("private", encoding="utf-8")
    object.__setattr__(container.ingestion, "_ingest_root", tmp_path / "corpus")

    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Alpha"})
        response = client.post(
            "/workspaces/alpha/ingest", json={"paths": [str(outside)]}
        )

    assert response.status_code == 400
    assert "outside the permitted ingestion root" in response.json()["detail"]


def test_the_bundled_examples_remain_ingestable(container) -> None:
    """The security fix must not break the documented example workflow."""
    examples = Path(__file__).resolve().parents[1] / "examples" / "solar"
    object.__setattr__(container.ingestion, "_ingest_root", examples.parent.parent)

    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Alpha"})
        response = client.post(
            "/workspaces/alpha/ingest", json={"paths": [str(examples)]}
        )

    assert response.status_code == 201
    assert response.json()["documents_ingested"] == 3


# --- atomic persistence -----------------------------------------------------


def test_write_json_atomically_leaves_no_partial_file(tmp_path) -> None:
    target = tmp_path / "nested" / "data.json"
    write_json_atomically(target, [{"a": 1}])
    assert json.loads(target.read_text(encoding="utf-8")) == [{"a": 1}]
    # rewriting replaces cleanly and leaves no temp file behind
    write_json_atomically(target, [{"a": 2}])
    assert json.loads(target.read_text(encoding="utf-8")) == [{"a": 2}]
    assert list(target.parent.iterdir()) == [target]


def test_registry_survives_a_corrupt_store(tmp_path) -> None:
    path = tmp_path / "workspaces.json"
    path.write_text("{not json", encoding="utf-8")
    assert WorkspaceRegistry(path).list() == []


# --- workspace state --------------------------------------------------------


def test_ingestion_is_recorded_on_the_workspace(tmp_path) -> None:
    registry = WorkspaceRegistry(tmp_path / "workspaces.json")
    registry.create("Alpha")
    updated = registry.record_ingestion(
        "alpha",
        [
            SourceDocument(content="a", file_name="one.md", source="file"),
            SourceDocument(content="b", file_name="two.md", source="file"),
        ],
    )
    assert {d.file_name for d in updated.documents} == {"one.md", "two.md"}
    assert updated.knowledge_updated_at is not None
    assert updated.graph_built is False

    # re-ingesting the same file replaces its record instead of duplicating it
    again = registry.record_ingestion(
        "alpha", [SourceDocument(content="a2", file_name="one.md", source="file")]
    )
    assert [d.file_name for d in again.documents].count("one.md") == 1
    assert len(again.documents) == 2

    built = registry.record_graph_built("alpha")
    assert built.graph_built is True
    # and it survives a reload from disk
    assert WorkspaceRegistry(tmp_path / "workspaces.json").get("alpha").graph_built


def test_workspace_and_document_endpoints(container, fake_knowledge) -> None:
    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Alpha"})
        client.post(
            "/workspaces/alpha/ingest",
            json={"documents": [{"content": "Tariffs fell.", "file_name": "a.md"}]},
        )

        workspace = client.get("/workspaces/alpha")
        assert workspace.status_code == 200
        body = workspace.json()
        assert body["document_count"] == 1
        assert body["knowledge_updated_at"]

        documents = client.get("/workspaces/alpha/documents")
        assert documents.status_code == 200
        assert [d["file_name"] for d in documents.json()] == ["a.md"]

        assert client.get("/workspaces/missing").status_code == 404
        assert client.get("/workspaces/missing/documents").status_code == 404


def test_building_the_graph_is_recorded(container) -> None:
    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Alpha"})
        assert client.get("/workspaces/alpha").json()["graph_built"] is False
        client.post("/workspaces/alpha/graph")
        assert client.get("/workspaces/alpha").json()["graph_built"] is True


# --- freshness --------------------------------------------------------------


def _workspace_with_docs(*, ingested_at) -> Workspace:
    return Workspace(
        workspace_id="alpha",
        name="Alpha",
        documents=(IngestedDocument(file_name="new.md", ingested_at=ingested_at),),
        knowledge_updated_at=ingested_at,
    )


def test_a_decision_is_fresh_when_nothing_was_ingested_after_it() -> None:
    decision = make_decision("alpha")
    workspace = _workspace_with_docs(
        ingested_at=decision.created_at.replace(year=decision.created_at.year - 1)
    )
    result = assess_freshness(decision, workspace)
    assert result.stale is False
    assert result.documents_added_since == []
    assert "No knowledge has been ingested" in result.summary


def test_a_decision_is_stale_when_knowledge_arrived_afterwards() -> None:
    decision = make_decision("alpha")
    workspace = _workspace_with_docs(
        ingested_at=decision.created_at.replace(year=decision.created_at.year + 1)
    )
    result = assess_freshness(decision, workspace)
    assert result.stale is True
    assert result.documents_added_since == ["new.md"]
    assert "Reassess" in result.summary


def test_freshness_is_unknown_for_a_workspace_with_no_documents() -> None:
    result = assess_freshness(make_decision("alpha"), Workspace("alpha", "Alpha"))
    assert result.stale is False
    assert "no recorded documents" in result.summary


def test_freshness_endpoint_reflects_new_ingestion(container, fake_knowledge) -> None:
    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Alpha"})
        decision = Decision(
            workspace_id="alpha",
            session_id="s1",
            question="Q",
            recommendation=Recommendation(statement="Do it"),
        )
        object.__setattr__(
            decision, "created_at", decision.created_at.replace(year=2000)
        )
        fake_knowledge.decisions["alpha"].append(decision)

        before = client.get(
            f"/workspaces/alpha/decisions/{decision.decision_id}/freshness"
        ).json()
        assert before["stale"] is False

        client.post(
            "/workspaces/alpha/ingest",
            json={"documents": [{"content": "New study.", "file_name": "study.md"}]},
        )
        after = client.get(
            f"/workspaces/alpha/decisions/{decision.decision_id}/freshness"
        ).json()

    assert after["stale"] is True
    assert after["documents_added_since"] == ["study.md"]


# --- provenance validation --------------------------------------------------


def test_evidence_attributed_to_an_unretrieved_source_is_an_error() -> None:
    from app.decisions.models import Evidence

    decision = make_decision(
        "alpha",
        evidence=[
            Evidence(evidence_id="E1", statement="ok", source="market.md"),
            Evidence(evidence_id="E2", statement="invented", source="ghost.md"),
        ],
    )
    issues = validate_decision(decision).errors
    codes = {i.code for i in issues}
    assert "EVIDENCE_SOURCE_UNKNOWN" in codes
    assert any("ghost.md" in i.message for i in issues)


def test_source_attribution_is_not_checked_when_no_sources_were_recorded() -> None:
    decision = make_decision("alpha")
    object.__setattr__(decision, "sources", [])
    codes = {i.code for i in validate_decision(decision).errors}
    assert "EVIDENCE_SOURCE_UNKNOWN" not in codes


# --- CORS -------------------------------------------------------------------


def test_cors_allows_the_configured_origin_and_no_other(container, settings) -> None:
    object.__setattr__(settings, "cors_allow_origins", ("http://localhost:5173",))
    app = create_app(container)
    with TestClient(app) as client:
        allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
        assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

        other = client.get("/health", headers={"Origin": "https://evil.example"})
        assert other.headers.get("access-control-allow-origin") is None


def test_documents_loaded_from_paths_are_recorded_too(container) -> None:
    """Regression: only inline documents used to reach the workspace record,
    so ingesting a directory left the corpus list and freshness clock empty."""
    examples = Path(__file__).resolve().parents[1] / "examples" / "solar"
    object.__setattr__(container.ingestion, "_ingest_root", examples.parent.parent)

    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Alpha"})
        client.post("/workspaces/alpha/ingest", json={"paths": [str(examples)]})

        documents = client.get("/workspaces/alpha/documents").json()
        workspace = client.get("/workspaces/alpha").json()

    assert {d["file_name"] for d in documents} == {
        "competitors.txt",
        "market_overview.md",
        "regulatory_notes.md",
    }
    assert workspace["document_count"] == 3
    assert workspace["knowledge_updated_at"] is not None


def test_chat_maps_provider_failures_consistently(container, settings) -> None:
    """A provider-side failure is 502 on /chat, as it already was on /decisions.

    The client itself is faked, so the mapping inside AnswerGenerator is what
    gets exercised rather than being bypassed.
    """
    import httpx as _httpx
    from openai import APIConnectionError, RateLimitError

    from app.agent.generator import AnswerGenerator

    request = _httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")

    def generator_raising(error: Exception) -> AnswerGenerator:
        generator = AnswerGenerator(settings)

        async def create(**_kwargs):
            raise error

        generator._client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": type("C", (), {"create": staticmethod(create)})()})()},
        )()
        return generator

    cases = [
        (APIConnectionError(request=request), 502, None),
        (TimeoutError("stage timed out"), 504, None),
        (
            RateLimitError(
                "429",
                response=_httpx.Response(429, headers={"retry-after": "12"}, request=request),
                body=None,
            ),
            429,
            "12",
        ),
    ]

    for error, expected_status, retry_after in cases:
        object.__setattr__(container.agent, "_generator", generator_raising(error))
        app = create_app(container)
        with TestClient(app) as client:
            client.post("/workspaces", json={"name": "Alpha"})
            response = client.post("/workspaces/alpha/chat", json={"message": "hi"})
        assert response.status_code == expected_status, error
        if retry_after:
            assert response.headers["retry-after"] == retry_after


def test_missing_credentials_are_reported_as_a_provider_failure(settings) -> None:
    from app.agent.generator import AnswerGenerator
    from app.decisions.analyst import DecisionAnalysisError

    object.__setattr__(settings, "openrouter_api_key", None)
    object.__setattr__(settings, "openai_api_key", None)
    with pytest.raises(DecisionAnalysisError, match="No LLM credentials"):
        AnswerGenerator(settings)._get_client()


# --- workspace-level freshness ----------------------------------------------


def test_workspace_freshness_aggregates_its_decisions() -> None:
    from app.decisions.freshness import assess_workspace_freshness

    fresh_decision = make_decision("alpha")
    stale_decision = make_decision("alpha")
    object.__setattr__(
        stale_decision, "created_at", stale_decision.created_at.replace(year=2000)
    )
    workspace = _workspace_with_docs(ingested_at=fresh_decision.created_at)

    result = assess_workspace_freshness(workspace, [fresh_decision, stale_decision])

    assert result.workspace_id == "alpha"
    assert result.document_count == 1
    assert result.decision_count == 2
    assert result.stale_decision_count == 1
    assert [d.decision_id for d in result.stale_decisions] == [
        stale_decision.decision_id
    ]
    assert "1 of 2 decisions" in result.summary


def test_workspace_freshness_reports_the_empty_cases() -> None:
    from app.decisions.freshness import assess_workspace_freshness

    no_documents = assess_workspace_freshness(Workspace("alpha", "Alpha"), [])
    assert no_documents.stale_decision_count == 0
    assert "no recorded documents" in no_documents.summary

    decision = make_decision("alpha")
    no_decisions = assess_workspace_freshness(
        _workspace_with_docs(ingested_at=decision.created_at), []
    )
    assert no_decisions.decision_count == 0
    assert "No decisions have been recorded" in no_decisions.summary


def test_workspace_freshness_endpoint(container, fake_knowledge) -> None:
    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Alpha"})

        empty = client.get("/workspaces/alpha/freshness")
        assert empty.status_code == 200
        assert empty.json()["stale_decision_count"] == 0

        decision = Decision(
            workspace_id="alpha",
            session_id="s1",
            question="Q",
            recommendation=Recommendation(statement="Do it"),
        )
        object.__setattr__(
            decision, "created_at", decision.created_at.replace(year=2000)
        )
        fake_knowledge.decisions["alpha"].append(decision)

        client.post(
            "/workspaces/alpha/ingest",
            json={"documents": [{"content": "New study.", "file_name": "study.md"}]},
        )
        body = client.get("/workspaces/alpha/freshness").json()

        assert client.get("/workspaces/missing/freshness").status_code == 404

    assert body["document_count"] == 1
    assert body["decision_count"] == 1
    assert body["stale_decision_count"] == 1
    assert body["stale_decisions"][0]["decision_id"] == decision.decision_id
    assert body["stale_decisions"][0]["documents_added_since"] == ["study.md"]
    assert body["knowledge_updated_at"] is not None


def test_the_decision_level_freshness_route_still_works(container, fake_knowledge) -> None:
    """The workspace route is additive; the per-decision one is unchanged."""
    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Alpha"})
        decision = make_decision("alpha")
        fake_knowledge.decisions["alpha"].append(decision)
        response = client.get(
            f"/workspaces/alpha/decisions/{decision.decision_id}/freshness"
        )

    assert response.status_code == 200
    assert response.json()["decision_id"] == decision.decision_id


def test_workspace_freshness_summary_reads_grammatically() -> None:
    from app.decisions.freshness import assess_workspace_freshness

    def summary_for(total: int, stale: int) -> str:
        decisions = [make_decision("alpha") for _ in range(total)]
        for decision in decisions[:stale]:
            object.__setattr__(
                decision, "created_at", decision.created_at.replace(year=2000)
            )
        # ingest after every decision, so the backdated ones read as stale
        latest = max(d.created_at for d in decisions)
        workspace = _workspace_with_docs(ingested_at=latest.replace(year=2099))
        return assess_workspace_freshness(workspace, decisions).summary

    assert "1 of 1 decision was made" in summary_for(1, 1)
    assert "2 of 2 decisions were made" in summary_for(2, 2)

    # and the all-fresh branch agrees too
    fresh = make_decision("alpha")
    workspace = _workspace_with_docs(
        ingested_at=fresh.created_at.replace(year=2000)
    )
    assert (
        assess_workspace_freshness(workspace, [fresh]).summary
        == "No knowledge has been ingested since this decision was made."
    )
    assert "these decisions were made" in assess_workspace_freshness(
        workspace, [fresh, make_decision("alpha")]
    ).summary
