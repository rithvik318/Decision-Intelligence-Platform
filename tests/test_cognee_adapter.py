"""Verify the adapter translates application calls to Cognee's public API.

A stub module stands in for `cognee` so the test stays offline and fast.
"""

from __future__ import annotations

import sys
import types

import pytest

from app.config import Settings


class _StubCognee(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("cognee")
        # Keep the real package's __path__ so `cognee.tasks...` submodule
        # imports still resolve; only the top-level entry points are stubbed.
        import cognee as real_cognee

        self.__path__ = real_cognee.__path__
        self.calls: list[tuple[str, dict]] = []
        self.SearchType = types.SimpleNamespace(
            CHUNKS="CHUNKS", GRAPH_COMPLETION="GRAPH_COMPLETION"
        )

    async def add(self, payload, **kwargs):
        self.calls.append(("add", {"payload": payload, **kwargs}))

    async def cognify(self, **kwargs):
        self.calls.append(("cognify", kwargs))

    async def run_custom_pipeline(self, **kwargs):
        self.calls.append(("run_custom_pipeline", kwargs))

    async def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        return [{"text": "solar evidence", "score": 0.9, "file_name": "a.md"}]

    async def remember(self, content, **kwargs):
        self.calls.append(("remember", {"content": content, **kwargs}))

    async def recall(self, **kwargs):
        self.calls.append(("recall", kwargs))
        return ["previously discussed grid capacity"]


@pytest.fixture
def cognee_service(monkeypatch, tmp_path):
    stub = _StubCognee()
    monkeypatch.setitem(sys.modules, "cognee", stub)
    from app.knowledge.cognee_service import CogneeKnowledgeService

    service = CogneeKnowledgeService(Settings(data_dir=tmp_path))
    return service, stub


async def test_ingest_indexes_chunks_without_calling_the_llm(
    cognee_service, solar_documents
):
    """Default ingest: add + the LLM-free chunk pipeline, no cognify."""
    service, stub = cognee_service
    result = await service.ingest("Solar Market Analysis", solar_documents)
    assert result.dataset == "workspace-solar-market-analysis"
    assert result.documents_ingested == 2
    assert result.graph_built is False

    add, pipeline = stub.calls
    assert add[0] == "add" and add[1]["dataset_name"] == result.dataset
    assert "file_name: market_overview.md" in add[1]["payload"][0]

    assert pipeline[0] == "run_custom_pipeline"
    assert pipeline[1]["dataset"] == result.dataset
    assert pipeline[1]["skip_connection_test"] is True
    executables = [task.executable.__name__ for task in pipeline[1]["tasks"]]
    assert executables == [
        "classify_documents",
        "extract_chunks_from_documents",
        "add_data_points",
    ]
    # the one LLM-bound task of the default pipeline is deliberately absent
    assert "extract_graph_and_summarize" not in executables


async def test_ingest_can_opt_into_graph_enrichment(cognee_service, solar_documents):
    service, stub = cognee_service
    result = await service.ingest(
        "Solar Market Analysis", solar_documents, build_graph=True
    )
    assert result.graph_built is True
    add, cognify = stub.calls
    assert add[0] == "add"
    assert cognify[0] == "cognify"
    assert cognify[1]["datasets"] == [result.dataset]
    # concurrency is bounded rather than Cognee's default of 2000
    assert cognify[1]["chunks_per_batch"] == 4


async def test_searches_are_dataset_scoped_and_normalized(cognee_service):
    service, stub = cognee_service
    semantic = await service.semantic_search("solar", "tariffs")
    graph = await service.graph_search("solar", "tariffs")
    assert semantic[0].text == "solar evidence"
    assert semantic[0].retrieval_type == "semantic"
    assert semantic[0].source == "a.md"
    assert graph[0].retrieval_type == "graph"
    assert stub.calls[0][1]["query_type"] == "CHUNKS"
    assert stub.calls[1][1]["query_type"] == "GRAPH_COMPLETION"
    assert stub.calls[1][1]["only_context"] is True


async def test_memory_is_session_scoped(cognee_service):
    service, stub = cognee_service
    await service.remember("solar", "s1", "grid capacity is a risk")
    recalled = await service.recall("solar", "s1", "grid")
    assert recalled[0].retrieval_type == "memory"
    remember_call, recall_call = stub.calls
    assert remember_call[1]["session_id"] == "workspace:solar:session:s1"
    assert recall_call[1]["session_id"] == "workspace:solar:session:s1"


async def test_blank_workspace_id_is_rejected(cognee_service):
    service, _ = cognee_service
    with pytest.raises(ValueError):
        await service.semantic_search("  ", "anything")


async def test_decisions_reach_both_cognee_memory_and_the_structured_store(
    cognee_service,
) -> None:
    from app.decisions.models import Decision, Recommendation

    service, stub = cognee_service
    decision = Decision(
        workspace_id="solar",
        session_id="s1",
        question="Residential or commercial?",
        recommendation=Recommendation(statement="Commercial", rationale="EPC."),
    )
    await service.store_decision("solar", "s1", decision)

    remember_call = stub.calls[0]
    assert remember_call[0] == "remember"
    assert "Recommendation: Commercial" in remember_call[1]["content"]
    assert remember_call[1]["session_id"] == "workspace:solar:session:s1"

    restored = await service.load_decisions("solar")
    assert [d.decision_id for d in restored] == [decision.decision_id]
    assert await service.load_decisions("other") == []
