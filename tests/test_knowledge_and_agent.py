from __future__ import annotations

from pathlib import Path

from app.domain import RetrievalContext
from app.ingestion.files import load_directory, load_file
from tests.fakes import InMemoryKnowledgeFake

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "solar"


async def test_knowledge_and_memory_are_workspace_scoped(
    fake_knowledge: InMemoryKnowledgeFake, solar_documents
) -> None:
    await fake_knowledge.ingest("solar", solar_documents)
    semantic = await fake_knowledge.semantic_search("solar", "feed-in tariffs")
    graph = await fake_knowledge.graph_search("solar", "Nordlicht modules supplier")
    assert "Feed-in tariffs" in semantic[0].text
    assert any("depends on imported modules" in item.text for item in graph)

    await fake_knowledge.remember("solar", "s1", "Grid connection risk was noted")
    assert await fake_knowledge.recall("solar", "s1", "grid connection")
    assert not await fake_knowledge.recall("other", "s1", "grid connection")


async def test_agent_runs_langgraph_and_reports_hits(
    container, fake_knowledge, solar_documents
) -> None:
    await fake_knowledge.ingest("solar", solar_documents)
    result = await container.agent.run(
        "Which competitors depend on suppliers?", "solar", "s1"
    )
    assert result.semantic_hits >= 1
    assert result.sources
    assert fake_knowledge.memories[("solar", "s1")]


async def test_agent_retries_once_when_context_is_empty(container, generator) -> None:
    result = await container.agent.run("anything at all", "empty-workspace", "s1")
    assert result.semantic_hits == 0
    # one initial attempt plus exactly one bounded refinement
    assert len(generator.calls) == 2
    assert "No evidence" in result.answer


def test_example_files_load_with_provenance() -> None:
    documents = load_directory(EXAMPLES)
    assert {d.file_name for d in documents} == {
        "competitors.txt",
        "market_overview.md",
        "regulatory_notes.md",
    }
    single = load_file(EXAMPLES / "market_overview.md")
    assert single.document_type == "markdown"
    assert single.source == "file"
    assert single.location.endswith("market_overview.md")
    assert single.timestamp
    assert "file_name: market_overview.md" in single.as_knowledge_text()


def test_retrieval_context_prompt_block_is_numbered() -> None:
    empty = RetrievalContext(query="q", workspace_id="w")
    assert empty.as_prompt_block() == "(no context retrieved)"
