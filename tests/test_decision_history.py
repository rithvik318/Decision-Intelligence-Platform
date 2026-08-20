"""Phase 3: decision history, comparison, provenance and validation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.decisions.comparison import compare_decisions
from app.decisions.models import (
    Alternative,
    Assumption,
    Claim,
    Decision,
    DecisionStatus,
    Evidence,
    Level,
    Recommendation,
    Risk,
)
from app.decisions.provenance import build_provenance
from app.decisions.store import DecisionStore
from app.decisions.validation import validate_decision
from app.main import create_app

# Unicode punctuation the Phase 2 charset fix has to keep intact.
UNICODE = "Feed-in tariff’s 30 kWp cap — “binds” 2024–2027."


def make_decision(
    workspace_id: str = "alpha",
    *,
    question: str = "Residential or commercial?",
    recommendation: str = "Commercial",
    confidence: Level = Level.MEDIUM,
    evidence: list[Evidence] | None = None,
    claims: list[Claim] | None = None,
    assumptions: list[str] = (),
    risks: list[Risk] | None = None,
    alternatives: list[Alternative] | None = None,
    status: DecisionStatus = DecisionStatus.PROPOSED,
    supersedes: str | None = None,
    changed_since_previous: list[str] = (),
) -> Decision:
    if evidence is None:
        evidence = [
            Evidence(evidence_id="E1", statement="Tariffs declined", source="market.md"),
            Evidence(evidence_id="E2", statement="Grid queues delay", source="notes.md"),
        ]
    if claims is None:
        claims = [Claim(statement="Commercial scales better", supporting_evidence=["E1"])]
    if alternatives is None:
        alternatives = [
            Alternative(name="Commercial", advantages=["EPC"], disadvantages=["Price"],
                        evidence=["E1"])
        ]
    return Decision(
        workspace_id=workspace_id,
        session_id="s1",
        question=question,
        status=status,
        recommendation=Recommendation(
            statement=recommendation, rationale="Grounded.", confidence=confidence
        ),
        evidence=list(evidence),
        claims=list(claims),
        assumptions=[Assumption(statement=a) for a in assumptions],
        risks=list(risks or []),
        alternatives=list(alternatives),
        sources=["market.md", "notes.md"],
        supersedes=supersedes,
        changed_since_previous=list(changed_since_previous),
    )


@pytest.fixture
def seeded(container, fake_knowledge):
    """Two decisions in workspace alpha, one in beta."""
    first = make_decision("alpha", recommendation="Residential", confidence=Level.LOW)
    second = make_decision(
        "alpha",
        recommendation="Commercial",
        confidence=Level.HIGH,
        status=DecisionStatus.REASSESSED,
        supersedes=first.decision_id,
        changed_since_previous=["Grid constraint now rated high"],
        assumptions=["Conditions persist"],
        risks=[Risk(statement="Capacity", rationale="See E1")],
    )
    other = make_decision("beta", recommendation="Beta only")
    fake_knowledge.decisions["alpha"].extend([first, second])
    fake_knowledge.decisions["beta"].append(other)
    return first, second, other


@pytest.fixture
def client(container):
    app = create_app(container)
    with TestClient(app) as test_client:
        test_client.post("/workspaces", json={"name": "Alpha"})
        test_client.post("/workspaces", json={"name": "Beta"})
        yield test_client


# --- store ------------------------------------------------------------------


def test_store_get_is_workspace_scoped_and_round_trips(tmp_path) -> None:
    store = DecisionStore(tmp_path / "decisions.json")
    mine = make_decision("alpha", question=UNICODE)
    theirs = make_decision("beta")
    store.append(mine)
    store.append(theirs)

    assert store.get("alpha", mine.decision_id).question == UNICODE
    # present in the file, but not reachable from the wrong workspace
    assert store.get("alpha", theirs.decision_id) is None
    assert store.get("alpha", "nope") is None
    assert store.known_ids("alpha") == {mine.decision_id}


def test_store_orders_newest_first_and_survives_a_bad_record(tmp_path) -> None:
    path = tmp_path / "decisions.json"
    store = DecisionStore(path)
    older = make_decision("alpha", recommendation="Older")
    newer = make_decision("alpha", recommendation="Newer")
    object.__setattr__(newer, "created_at", older.created_at.replace(year=2030))
    store.append(older)
    store.append(newer)

    import json

    records = json.loads(path.read_text(encoding="utf-8"))
    records.append({"workspace_id": "alpha", "decision_id": "junk"})  # malformed
    path.write_text(json.dumps(records), encoding="utf-8")

    listed = store.list_for_workspace("alpha")
    assert [d.recommendation.statement for d in listed] == ["Newer", "Older"]


def test_store_tolerates_an_unreadable_file(tmp_path) -> None:
    path = tmp_path / "decisions.json"
    path.write_text("{not json", encoding="utf-8")
    assert DecisionStore(path).list_for_workspace("alpha") == []


# --- comparison -------------------------------------------------------------


def test_comparison_reports_every_changed_dimension(seeded) -> None:
    first, second, _ = seeded
    result = compare_decisions(first, second)

    assert result.left_decision_id == first.decision_id
    assert result.right_decision_id == second.decision_id
    assert result.right_supersedes_left is True
    assert result.recommendation_changed is True
    assert (result.left_recommendation, result.right_recommendation) == (
        "Residential",
        "Commercial",
    )
    assert result.confidence_changed is True
    assert (result.left_confidence, result.right_confidence) == (Level.LOW, Level.HIGH)
    assert result.status_changed is True
    assert result.added_assumptions == ["Conditions persist"]
    assert result.added_risks == ["Capacity"]
    assert result.changed_since_previous == ["Grid constraint now rated high"]


def test_comparison_of_identical_decisions_reports_no_change() -> None:
    left = make_decision("alpha")
    right = make_decision("alpha")
    result = compare_decisions(left, right)
    assert not result.recommendation_changed
    assert not result.confidence_changed
    assert not result.status_changed
    assert result.added_evidence == result.removed_evidence == []
    assert result.added_claims == result.removed_claims == []
    assert result.right_supersedes_left is False


def test_comparison_tracks_evidence_claims_and_alternatives() -> None:
    left = make_decision("alpha")
    right = make_decision(
        "alpha",
        evidence=[
            Evidence(evidence_id="E1", statement="Tariffs declined", source="market.md"),
            Evidence(evidence_id="E9", statement="New auction rules", source="reg.md"),
        ],
        claims=[Claim(statement="Rules favour scale", supporting_evidence=["E9"])],
        alternatives=[Alternative(name="Utility", advantages=["Volume"])],
    )
    result = compare_decisions(left, right)
    assert result.added_evidence == ["New auction rules"]
    assert result.removed_evidence == ["Grid queues delay"]
    assert result.added_claims == ["Rules favour scale"]
    assert result.removed_claims == ["Commercial scales better"]
    assert result.added_alternatives == ["Utility"]
    assert result.removed_alternatives == ["Commercial"]


# --- provenance -------------------------------------------------------------


def test_provenance_chains_recommendation_to_claims_to_evidence_to_source() -> None:
    decision = make_decision("alpha")
    result = build_provenance(decision)

    assert result.recommendation.statement == "Commercial"
    claim = result.recommendation.claims[0]
    assert claim.statement == "Commercial scales better"
    assert [e.evidence_id for e in claim.evidence] == ["E1"]
    assert claim.evidence[0].source == "market.md"
    assert claim.evidence[0].relevance is Level.MEDIUM
    assert claim.unresolved_evidence_ids == []
    # E2 exists but no claim cites it
    assert result.uncited_evidence_ids == ["E2"]


def test_provenance_flags_a_claim_citing_unknown_evidence() -> None:
    decision = make_decision(
        "alpha",
        claims=[Claim(statement="Unbacked", supporting_evidence=["E1", "E77"])],
    )
    claim = build_provenance(decision).recommendation.claims[0]
    assert [e.evidence_id for e in claim.evidence] == ["E1"]
    assert claim.unresolved_evidence_ids == ["E77"]


def test_provenance_of_a_decision_with_no_evidence_is_empty_not_invented() -> None:
    decision = make_decision("alpha", evidence=[], claims=[])
    result = build_provenance(decision)
    assert result.recommendation.claims == []
    assert result.uncited_evidence_ids == []


# --- validation -------------------------------------------------------------


def test_a_well_formed_decision_validates() -> None:
    result = validate_decision(make_decision("alpha"))
    assert result.valid is True
    assert result.errors == []


def test_missing_recommendation_is_an_error() -> None:
    decision = make_decision("alpha", recommendation=" ")
    codes = {e.code for e in validate_decision(decision).errors}
    assert "RECOMMENDATION_MISSING" in codes


def test_claims_must_cite_evidence_that_exists() -> None:
    decision = make_decision(
        "alpha",
        claims=[
            Claim(statement="No backing", supporting_evidence=[]),
            Claim(statement="Bad backing", supporting_evidence=["E42"]),
        ],
    )
    result = validate_decision(decision)
    codes = {e.code for e in result.errors}
    assert codes == {"CLAIM_MISSING_EVIDENCE", "CLAIM_UNKNOWN_EVIDENCE"}
    assert result.valid is False


def test_alternative_and_risk_references_must_resolve() -> None:
    decision = make_decision(
        "alpha",
        alternatives=[Alternative(name="Ghost", advantages=["x"], evidence=["E99"])],
        risks=[Risk(statement="Vague", rationale="Per E88 the queue is long")],
    )
    codes = {e.code for e in validate_decision(decision).errors}
    assert codes == {"ALTERNATIVE_UNKNOWN_EVIDENCE", "RISK_UNKNOWN_EVIDENCE"}


def test_evidence_without_a_source_is_a_warning_not_an_error() -> None:
    decision = make_decision(
        "alpha",
        evidence=[Evidence(evidence_id="E1", statement="Unsourced", source=None)],
        claims=[Claim(statement="c", supporting_evidence=["E1"])],
    )
    result = validate_decision(decision)
    assert result.valid is True
    assert "EVIDENCE_MISSING_SOURCE" in {w.code for w in result.warnings}


def test_reassessment_bookkeeping_must_be_consistent() -> None:
    stray = make_decision("alpha", changed_since_previous=["something"])
    assert "CHANGED_WITHOUT_REASSESSMENT" in {
        e.code for e in validate_decision(stray).errors
    }

    dangling = make_decision(
        "alpha", status=DecisionStatus.REASSESSED, supersedes="not-a-decision"
    )
    assert "SUPERSEDES_UNKNOWN_DECISION" in {
        e.code for e in validate_decision(dangling, known_decision_ids=set()).errors
    }

    orphan = make_decision("alpha", status=DecisionStatus.REASSESSED)
    assert "REASSESSMENT_WITHOUT_SUPERSEDES" in {
        w.code for w in validate_decision(orphan).warnings
    }


def test_duplicate_evidence_ids_are_rejected() -> None:
    decision = make_decision(
        "alpha",
        evidence=[
            Evidence(evidence_id="E1", statement="a", source="s"),
            Evidence(evidence_id="E1", statement="b", source="s"),
        ],
    )
    assert "EVIDENCE_DUPLICATE_ID" in {e.code for e in validate_decision(decision).errors}


# --- API --------------------------------------------------------------------


def test_history_endpoints_return_workspace_scoped_decisions(client, seeded) -> None:
    first, second, _ = seeded

    listed = client.get("/workspaces/alpha/decisions")
    assert listed.status_code == 200
    assert [d["decision_id"] for d in listed.json()] == [
        second.decision_id,
        first.decision_id,
    ]

    single = client.get(f"/workspaces/alpha/decisions/{first.decision_id}")
    assert single.status_code == 200
    assert single.json()["recommendation"]["statement"] == "Residential"

    assert client.get("/workspaces/alpha/decisions/missing").status_code == 404


def test_comparison_provenance_and_validation_endpoints(client, seeded) -> None:
    first, second, _ = seeded

    comparison = client.get(
        f"/workspaces/alpha/decisions/{first.decision_id}/compare/{second.decision_id}"
    )
    assert comparison.status_code == 200
    assert comparison.json()["recommendation_changed"] is True

    provenance = client.get(f"/workspaces/alpha/decisions/{first.decision_id}/provenance")
    assert provenance.status_code == 200
    assert provenance.json()["recommendation"]["claims"][0]["evidence"][0][
        "source"
    ] == "market.md"

    validation = client.get(f"/workspaces/alpha/decisions/{first.decision_id}/validation")
    assert validation.status_code == 200
    assert validation.json()["valid"] is True


def test_validation_endpoint_resolves_supersedes_within_the_workspace(
    client, seeded
) -> None:
    _, second, _ = seeded
    body = client.get(
        f"/workspaces/alpha/decisions/{second.decision_id}/validation"
    ).json()
    # `second` supersedes `first`, which is in the same workspace
    assert "SUPERSEDES_UNKNOWN_DECISION" not in {e["code"] for e in body["errors"]}


def test_no_endpoint_leaks_another_workspaces_decision(client, seeded) -> None:
    first, _, other = seeded
    foreign = other.decision_id

    assert client.get(f"/workspaces/alpha/decisions/{foreign}").status_code == 404
    assert (
        client.get(
            f"/workspaces/alpha/decisions/{first.decision_id}/compare/{foreign}"
        ).status_code
        == 404
    )
    assert client.get(f"/workspaces/alpha/decisions/{foreign}/provenance").status_code == 404
    assert client.get(f"/workspaces/alpha/decisions/{foreign}/validation").status_code == 404
    assert (
        client.post(
            f"/workspaces/alpha/decisions/{foreign}/reassess", json={}
        ).status_code
        == 404
    )
    # and alpha's history never mentions it
    assert foreign not in {d["decision_id"] for d in client.get("/workspaces/alpha/decisions").json()}


def test_phase3_responses_preserve_unicode(client, container, fake_knowledge) -> None:
    decision = make_decision("alpha", question=UNICODE)
    object.__setattr__(decision.recommendation, "statement", UNICODE)
    fake_knowledge.decisions["alpha"].append(decision)

    response = client.get(f"/workspaces/alpha/decisions/{decision.decision_id}/provenance")
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.json()["question"] == UNICODE
    assert response.json()["recommendation"]["statement"] == UNICODE


# --- regression: list saw a decision that get-by-id could not find -----------


def test_every_listed_decision_is_retrievable_by_id(client, seeded) -> None:
    """A decision visible in the history must be fetchable individually.

    Regression for a report of `GET /decisions` returning a reassessed and a
    proposed decision while `GET /decisions/{id}` answered 404 for one of them.
    The two paths must agree, in both directions, for every status.
    """
    _first, _second, other = seeded

    listed = client.get("/workspaces/alpha/decisions").json()
    assert {d["status"] for d in listed} == {"proposed", "reassessed"}

    for summary in listed:
        fetched = client.get(f"/workspaces/alpha/decisions/{summary['decision_id']}")
        assert fetched.status_code == 200, summary["decision_id"]
        # the same object, not merely the same id
        assert fetched.json() == summary

    # an id that exists nowhere
    assert client.get("/workspaces/alpha/decisions/does-not-exist").status_code == 404
    # an id that exists, but in another workspace
    assert client.get(f"/workspaces/alpha/decisions/{other.decision_id}").status_code == 404
    # ...and is still reachable from its own workspace, so it was never lost
    assert client.get(f"/workspaces/beta/decisions/{other.decision_id}").status_code == 200
