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
        self.calls: list[tuple[str, dict]] = []
        self.SearchType = types.SimpleNamespace(
            CHUNKS="CHUNKS", GRAPH_COMPLETION="GRAPH_COMPLETION"
        )

    async def add(self, payload, **kwargs):
        self.calls.append(("add", {"payload": payload, **kwargs}))

    async def cognify(self, **kwargs):
        self.calls.append(("cognify", kwargs))

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


async def test_ingest_uses_workspace_scoped_dataset(cognee_service, solar_documents):
    service, stub = cognee_service
    result = await service.ingest("Solar Market Analysis", solar_documents)
    assert result.dataset == "workspace-solar-market-analysis"
    assert result.documents_ingested == 2
    add, cognify = stub.calls
    assert add[0] == "add" and add[1]["dataset_name"] == result.dataset
    assert "file_name: market_overview.md" in add[1]["payload"][0]
    assert cognify[1]["datasets"] == [result.dataset]


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
