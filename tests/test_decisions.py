"""Phase 2: the decision intelligence layer."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.decisions.models import (
    Decision,
    DecisionStatus,
    Level,
    Recommendation,
)
from app.decisions.store import DecisionStore
from app.main import create_app

REASSESS = "Reassess our previous decision using current project knowledge."
QUESTION = "Should we prioritise residential or commercial solar projects?"


def _recommendation() -> Recommendation:
    return Recommendation(statement="Go commercial", rationale="EPC leverage.")


# --- 1. model validation ----------------------------------------------------


def test_decision_requires_a_recommendation_and_defaults_sensibly() -> None:
    decision = Decision(
        workspace_id="solar", session_id="s1", question=QUESTION,
        recommendation=_recommendation(),
    )
    assert decision.decision_id and decision.created_at
    assert decision.status is DecisionStatus.PROPOSED
    assert decision.evidence == [] and decision.supersedes is None

    with pytest.raises(ValidationError):
        Decision(workspace_id="solar", session_id="s1", question=QUESTION)


def test_levels_are_constrained() -> None:
    assert Recommendation(statement="x", confidence="high").confidence is Level.HIGH
    with pytest.raises(ValidationError):
        Recommendation(statement="x", confidence="extremely-high")


# --- 2-6. graph execution over fakes ---------------------------------------


@pytest.fixture
async def analysed(container, fake_knowledge, solar_documents):
    await fake_knowledge.ingest("solar", solar_documents)
    return await container.decision_agent.run(QUESTION, "solar", "s1")


async def test_graph_produces_a_fully_structured_decision(analysed, analyst) -> None:
    assert analysed.question == QUESTION
    assert analysed.evidence and analysed.claims
    assert analysed.assumptions and analysed.risks
    assert len(analysed.alternatives) == 2
    assert analysed.recommendation.statement == "Prioritise commercial rooftop"
    assert analysed.status is DecisionStatus.PROPOSED
    # every stage ran as its own node, in order
    assert analyst.calls == [
        "extract_evidence",
        "generate_claims",
        "identify_assumptions_and_risks",
        "evaluate_alternatives",
        "generate_recommendation",
    ]


async def test_evidence_is_grounded_in_retrieved_context(analysed) -> None:
    assert all(e.evidence_id.startswith("E") for e in analysed.evidence)
    assert any(e.source for e in analysed.evidence)
    assert analysed.sources  # provenance preserved from retrieval


async def test_claims_reference_evidence_ids(analysed) -> None:
    evidence_ids = {e.evidence_id for e in analysed.evidence}
    assert all(set(c.supporting_evidence) <= evidence_ids for c in analysed.claims)


async def test_alternatives_are_weighed_both_ways(analysed) -> None:
    for alternative in analysed.alternatives:
        assert alternative.advantages and alternative.disadvantages


# --- 6-7. persistence, recall, reassessment --------------------------------


async def test_decision_is_persisted_to_both_memory_layers(
    analysed, fake_knowledge
) -> None:
    stored = await fake_knowledge.load_decisions("solar")
    assert [d.decision_id for d in stored] == [analysed.decision_id]
    # the readable summary also reached Cognee session memory
    assert any("Recommendation:" in m for m in fake_knowledge.memories[("solar", "s1")])


async def test_previous_decisions_are_workspace_scoped(
    analysed, fake_knowledge
) -> None:
    assert await fake_knowledge.load_decisions("solar")
    assert await fake_knowledge.load_decisions("other-workspace") == []


async def test_reassessment_uses_the_previous_decision(
    analysed, container, analyst
) -> None:
    reassessment = await container.decision_agent.run(REASSESS, "solar", "s1")

    assert reassessment.status is DecisionStatus.REASSESSED
    assert reassessment.supersedes == analysed.decision_id
    assert reassessment.changed_since_previous
    # the prior decision was actually fed to the recommendation stage
    assert analysed.decision_id in analyst.previous_seen[-1]
    assert analysed.question in analyst.previous_seen[-1]


async def test_a_fresh_question_is_not_anchored_to_prior_decisions(
    analysed, container, analyst
) -> None:
    await container.decision_agent.run("Which supplier should we choose?", "solar", "s1")
    assert analyst.previous_seen[-1] == ""


async def test_empty_question_is_rejected(container) -> None:
    with pytest.raises(ValueError):
        await container.decision_agent.run("   ", "solar", "s1")


# --- retrieval refinement ---------------------------------------------------


async def test_thin_context_triggers_one_bounded_refinement(container, analyst) -> None:
    decision = await container.decision_agent.run(QUESTION, "empty-workspace", "s1")
    assert decision.evidence == []
    # refined once, then proceeded: analysis still ran exactly once per stage
    assert analyst.calls.count("extract_evidence") == 1


# --- store round-trip -------------------------------------------------------


def test_store_round_trips_a_decision_losslessly(tmp_path) -> None:
    store = DecisionStore(tmp_path / "decisions.json")
    original = Decision(
        workspace_id="solar", session_id="s1", question=QUESTION,
        recommendation=_recommendation(),
    )
    store.append(original)
    store.append(
        Decision(
            workspace_id="other", session_id="s1", question="x",
            recommendation=_recommendation(),
        )
    )
    restored = store.list_for_workspace("solar")
    assert len(restored) == 1
    assert restored[0].model_dump() == original.model_dump()


# --- 9. API -----------------------------------------------------------------


def test_decision_endpoints(container, fake_knowledge, solar_documents) -> None:
    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Solar"})
        client.post(
            "/workspaces/solar/ingest",
            json={
                "documents": [
                    {"content": d.content, "file_name": d.file_name}
                    for d in solar_documents
                ]
            },
        )

        created = client.post(
            "/workspaces/solar/decisions",
            json={"question": QUESTION, "session_id": "demo-1"},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["recommendation"]["statement"] == "Prioritise commercial rooftop"
        for key in ("evidence", "claims", "assumptions", "risks", "alternatives"):
            assert body[key], key

        listed = client.get("/workspaces/solar/decisions")
        assert listed.status_code == 200
        assert [d["decision_id"] for d in listed.json()] == [body["decision_id"]]

        assert client.post(
            "/workspaces/missing/decisions", json={"question": QUESTION}
        ).status_code == 404


def test_a_failed_analysis_stage_returns_502_not_a_fake_decision(container) -> None:
    from app.decisions.analyst import DecisionAnalysisError

    async def boom(*args, **kwargs):
        raise DecisionAnalysisError("model returned prose, not JSON")

    container.decision_agent._analyst.extract_evidence = boom
    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Solar"})
        response = client.post("/workspaces/solar/decisions", json={"question": QUESTION})

    assert response.status_code == 502
    assert "JSON" in response.json()["detail"]


# --- structured LLM output (no network) -------------------------------------


class _FakeCompletions:
    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        content = self._replies.pop(0)
        message = type("M", (), {"content": content})()
        return type("R", (), {"choices": [type("C", (), {"message": message})()]})()


def _analyst_with(replies: list[str], settings):
    from app.decisions.analyst import DecisionAnalyst

    analyst = DecisionAnalyst(settings)
    completions = _FakeCompletions(replies)
    analyst._client = type(
        "Client", (), {"chat": type("Chat", (), {"completions": completions})()}
    )()
    return analyst, completions


async def test_analyst_validates_json_and_tolerates_fences(settings) -> None:
    analyst, completions = _analyst_with(
        ['```json\n{"claims": [{"statement": "c", "supporting_evidence": ["E1"]}]}\n```'],
        settings,
    )
    result = await analyst.generate_claims("q", "E1: something")
    assert result.claims[0].statement == "c"
    assert completions.calls == 1


async def test_analyst_retries_once_then_fails_loudly(settings) -> None:
    from app.decisions.analyst import DecisionAnalysisError

    analyst, completions = _analyst_with(["not json", "still not json"], settings)
    with pytest.raises(DecisionAnalysisError):
        await analyst.generate_claims("q", "E1: something")
    assert completions.calls == 2


async def test_analyst_recovers_on_the_retry(settings) -> None:
    analyst, completions = _analyst_with(["oops", '{"claims": []}'], settings)
    assert (await analyst.generate_claims("q", "E1: x")).claims == []
    assert completions.calls == 2
