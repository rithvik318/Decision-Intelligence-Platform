"""The ingest endpoint must always return, even if Cognee stops responding."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class StalledKnowledge:
    """Cognee adapter whose bound has fired (see CogneeKnowledgeService._call)."""

    async def ingest(self, workspace_id, documents, *, build_graph=None):
        raise TimeoutError("cognee.cognify did not return")


def test_stalled_cognee_returns_504_instead_of_hanging(container) -> None:
    object.__setattr__(container.ingestion, "_knowledge", StalledKnowledge())
    app = create_app(container)

    with TestClient(app) as client:
        client.post("/workspaces", json={"name": "Solar Test"})
        response = client.post(
            "/workspaces/solar-test/ingest",
            json={"documents": [{"content": "Alpha.", "file_name": "a.md"}]},
        )

    assert response.status_code == 504
    assert "COGNEE_TIMEOUT_SECONDS" in response.json()["detail"]


async def test_adapter_bounds_a_cognee_call_that_never_returns(
    monkeypatch, tmp_path
) -> None:
    import sys
    import types

    monkeypatch.setitem(sys.modules, "cognee", types.ModuleType("cognee"))
    from app.knowledge.cognee_service import CogneeKnowledgeService

    service = CogneeKnowledgeService(
        Settings(data_dir=tmp_path, cognee_timeout_seconds=0.05)
    )

    async def never_returns():
        await asyncio.sleep(3600)

    with pytest.raises(TimeoutError):
        await service._call("cognify", never_returns())
