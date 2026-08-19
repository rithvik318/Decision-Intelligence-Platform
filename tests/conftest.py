from __future__ import annotations

import pytest

from app.config import Settings
from app.container import build_container
from app.domain import SourceDocument
from tests.fakes import EchoGenerator, FakeDecisionAnalyst, InMemoryKnowledgeFake


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        openai_api_key="test-key", openai_model="test-model", data_dir=tmp_path
    )


@pytest.fixture
def fake_knowledge() -> InMemoryKnowledgeFake:
    return InMemoryKnowledgeFake()


@pytest.fixture
def generator() -> EchoGenerator:
    return EchoGenerator()


@pytest.fixture
def analyst() -> FakeDecisionAnalyst:
    return FakeDecisionAnalyst()


@pytest.fixture
def container(settings, fake_knowledge, generator, analyst):
    return build_container(
        settings, knowledge=fake_knowledge, generator=generator, analyst=analyst
    )


@pytest.fixture
def solar_documents() -> list[SourceDocument]:
    return [
        SourceDocument(
            content=(
                "The German rooftop solar segment is growing. Feed-in tariffs "
                "declined since 2012. Grid connection queues delay projects."
            ),
            file_name="market_overview.md",
            document_type="markdown",
            source="file",
            location="examples/solar/market_overview.md",
        ),
        SourceDocument(
            content=(
                "Helios Energie depends on a single inverter supplier. "
                "Nordlicht Solar depends on imported modules. "
                "Weser PV competes with Nordlicht Solar for grid capacity."
            ),
            file_name="competitors.txt",
            document_type="text",
            source="file",
            location="examples/solar/competitors.txt",
        ),
    ]
