from __future__ import annotations

import pytest

from app.workspaces import WorkspaceRegistry, normalize_workspace_id


def test_workspace_ids_are_slugified_and_unique(tmp_path) -> None:
    registry = WorkspaceRegistry(tmp_path / "workspaces.json")
    workspace = registry.create("Solar Market Analysis", "German entry decision")
    assert workspace.workspace_id == "solar-market-analysis"
    assert workspace.description == "German entry decision"
    with pytest.raises(ValueError):
        registry.create("solar market analysis")


def test_workspaces_persist_across_instances(tmp_path) -> None:
    path = tmp_path / "workspaces.json"
    WorkspaceRegistry(path).create("Solar Market Analysis")
    reloaded = WorkspaceRegistry(path)
    assert reloaded.get("Solar Market Analysis").name == "Solar Market Analysis"
    assert len(reloaded.list()) == 1


def test_blank_ids_are_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_workspace_id("  ---  ")
