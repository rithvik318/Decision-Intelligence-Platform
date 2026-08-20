"""Phase 3: the explicit reassessment endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.decisions.analyst import DecisionAnalysisError
from app.decisions.models import DecisionStatus
from app.domain import LLMRateLimitError
from app.main import create_app

QUESTION = "Should we prioritise residential or commercial solar projects?"


def _client(container):
    app = create_app(container)
    client = TestClient(app)
    client.__enter__()
    client.post("/workspaces", json={"name": "Alpha"})
    client.post("/workspaces", json={"name": "Beta"})
    return client


async def _seed(container, fake_knowledge, solar_documents, workspace="alpha"):
    await fake_knowledge.ingest(workspace, solar_documents)
    return await container.decision_agent.run(QUESTION, workspace, "s1")


async def test_reassessment_links_supersedes_and_records_what_changed(
    container, fake_knowledge, solar_documents, analyst
) -> None:
    original = await _seed(container, fake_knowledge, solar_documents)
    client = _client(container)
    try:
        response = client.post(
            f"/workspaces/alpha/decisions/{original.decision_id}/reassess",
            json={"session_id": "demo-1"},
        )
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == DecisionStatus.REASSESSED.value
    assert body["supersedes"] == original.decision_id
    assert body["changed_since_previous"]
    assert body["decision_id"] != original.decision_id
    # the targeted decision actually reached the recommendation stage
    assert original.decision_id in analyst.previous_seen[-1]


async def test_reassessment_targets_the_named_decision_not_merely_the_newest(
    container, fake_knowledge, solar_documents
) -> None:
    older = await _seed(container, fake_knowledge, solar_documents)
    newer = await container.decision_agent.run("A later question?", "alpha", "s1")
    assert newer.decision_id != older.decision_id

    client = _client(container)
    try:
        body = client.post(
            f"/workspaces/alpha/decisions/{older.decision_id}/reassess", json={}
        ).json()
    finally:
        client.__exit__(None, None, None)

    assert body["supersedes"] == older.decision_id


async def test_the_default_question_is_used_when_none_is_supplied(
    container, fake_knowledge, solar_documents
) -> None:
    original = await _seed(container, fake_knowledge, solar_documents)
    client = _client(container)
    try:
        body = client.post(
            f"/workspaces/alpha/decisions/{original.decision_id}/reassess", json={}
        ).json()
    finally:
        client.__exit__(None, None, None)
    assert body["question"] == "Reassess this decision using current workspace knowledge."


async def test_reassessment_is_workspace_isolated(
    container, fake_knowledge, solar_documents
) -> None:
    foreign = await _seed(container, fake_knowledge, solar_documents, workspace="beta")
    client = _client(container)
    try:
        response = client.post(
            f"/workspaces/alpha/decisions/{foreign.decision_id}/reassess", json={}
        )
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 404
    # nothing was written into alpha
    assert await fake_knowledge.load_decisions("alpha") == []


def test_reassessing_a_missing_decision_is_404(container) -> None:
    client = _client(container)
    try:
        assert (
            client.post("/workspaces/alpha/decisions/nope/reassess", json={}).status_code
            == 404
        )
    finally:
        client.__exit__(None, None, None)


async def test_provider_errors_keep_their_phase_2_status_codes(
    container, fake_knowledge, solar_documents
) -> None:
    original = await _seed(container, fake_knowledge, solar_documents)
    path = f"/workspaces/alpha/decisions/{original.decision_id}/reassess"

    async def rate_limited(*args, **kwargs):
        raise LLMRateLimitError("provider rate-limited this request", "30")

    async def analysis_failed(*args, **kwargs):
        raise DecisionAnalysisError("model returned prose, not JSON")

    async def timed_out(*args, **kwargs):
        raise TimeoutError("stage timed out")

    client = _client(container)
    try:
        container.decision_agent._analyst.extract_evidence = rate_limited
        limited = client.post(path, json={})
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "30"

        container.decision_agent._analyst.extract_evidence = analysis_failed
        assert client.post(path, json={}).status_code == 502

        container.decision_agent._analyst.extract_evidence = timed_out
        assert client.post(path, json={}).status_code == 504
    finally:
        client.__exit__(None, None, None)
