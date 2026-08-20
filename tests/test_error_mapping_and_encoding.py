"""Provider rate limits map to 429; responses declare UTF-8."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import RateLimitError

from app.decisions.analyst import raise_if_rate_limited
from app.domain import LLMRateLimitError
from app.main import create_app

QUESTION = "Should we prioritise residential or commercial solar projects?"
# Curly quote, en dash, em dash and a narrow no-break space: the characters a
# latin-1-defaulting client turned into mojibake.
UNICODE_TEXT = "Prioritise commercial — the tariff’s 30 kWp cap “binds” 2024–2027."


def _rate_limit_error(retry_after: str | None = "30") -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after else {}
    response = httpx.Response(
        429,
        headers=headers,
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )
    return RateLimitError("rate limit exceeded", response=response, body=None)


# --- 1. rate-limit mapping --------------------------------------------------


def test_provider_429_is_translated_with_retry_after() -> None:
    with pytest.raises(LLMRateLimitError) as caught:
        raise_if_rate_limited(_rate_limit_error("30"), "generate_recommendation")
    assert caught.value.retry_after == "30"
    assert "rate-limited" in str(caught.value)
    assert "generate_recommendation" in str(caught.value)


def test_other_provider_errors_pass_through_untouched() -> None:
    raise_if_rate_limited(RuntimeError("connection reset"), "extract_evidence")


def test_decisions_endpoint_returns_429_not_500(container) -> None:
    async def rate_limited(*args, **kwargs):
        raise LLMRateLimitError("The LLM provider rate-limited this request.", "30")

    container.decision_agent._analyst.extract_evidence = rate_limited
    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Solar"})
        response = client.post("/workspaces/solar/decisions", json={"question": QUESTION})

    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    assert "rate-limited" in response.json()["detail"]


def test_chat_endpoint_returns_429_without_retry_after_header(container) -> None:
    async def rate_limited(*args, **kwargs):
        raise LLMRateLimitError("The LLM provider rate-limited this request.")

    container.agent._generator.generate = rate_limited
    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Solar"})
        response = client.post("/workspaces/solar/chat", json={"message": "hello"})

    assert response.status_code == 429
    assert "retry-after" not in response.headers


def test_timeout_behaviour_is_unchanged(container) -> None:
    """A stalled ingest still maps to 504, not 429."""
    async def stalled(*args, **kwargs):
        raise TimeoutError("cognee.cognify did not return")

    object.__setattr__(
        container.ingestion, "_knowledge", type("K", (), {"ingest": stalled})()
    )
    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Solar"})
        response = client.post(
            "/workspaces/solar/ingest",
            json={"documents": [{"content": "x", "file_name": "a.md"}]},
        )
    assert response.status_code == 504


# --- 2. encoding ------------------------------------------------------------


def test_json_responses_declare_utf8_and_survive_a_latin1_client(
    container, fake_knowledge
) -> None:
    from app.decisions.models import Decision, Recommendation

    decision = Decision(
        workspace_id="solar",
        session_id="s1",
        question=UNICODE_TEXT,
        recommendation=Recommendation(statement=UNICODE_TEXT, rationale=UNICODE_TEXT),
    )
    fake_knowledge.decisions["solar"].append(decision)

    app = create_app(container)
    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Solar"})
        response = client.get("/workspaces/solar/decisions")

    # the charset label is what a latin-1-defaulting client needs
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.encoding == "utf-8"
    assert response.json()[0]["question"] == UNICODE_TEXT
    # bytes on the wire are genuine UTF-8, not double-encoded
    assert UNICODE_TEXT.encode("utf-8") in response.content
    double_encoded = UNICODE_TEXT.encode("utf-8").decode("latin-1").encode("utf-8")
    assert double_encoded not in response.content


def test_decision_text_round_trips_through_the_store(tmp_path) -> None:
    from app.decisions.models import Decision, Recommendation
    from app.decisions.store import DecisionStore

    store = DecisionStore(tmp_path / "decisions.json")
    store.append(
        Decision(
            workspace_id="solar",
            session_id="s1",
            question=UNICODE_TEXT,
            recommendation=Recommendation(statement=UNICODE_TEXT),
        )
    )
    restored = store.list_for_workspace("solar")[0]
    assert restored.question == UNICODE_TEXT
    assert restored.recommendation.statement == UNICODE_TEXT
