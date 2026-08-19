from __future__ import annotations

import asyncio
import importlib
import json
import logging
import re
from collections.abc import Iterable
from typing import Any

from app.config import Settings
from app.domain import IngestResult, RetrievedItem, SourceDocument

logger = logging.getLogger(__name__)


class CogneeKnowledgeService:
    """Thin adapter around Cognee's public memory and retrieval APIs."""

    def __init__(self, settings: Settings) -> None:
        settings.configure_cognee_environment()
        self._timeout = settings.cognee_timeout_seconds
        try:
            self._cognee = importlib.import_module("cognee")
        except ImportError as exc:  # pragma: no cover - installation guard
            raise RuntimeError(
                "Cognee is not installed; run `pip install -e .`."
            ) from exc

    @staticmethod
    def _dataset(workspace_id: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", workspace_id.strip()).strip("-")
        if not safe:
            raise ValueError("workspace_id must contain at least one letter or number")
        return f"workspace-{safe.lower()}"

    @staticmethod
    def _session(workspace_id: str, session_id: str) -> str:
        return f"workspace:{workspace_id}:session:{session_id}"

    async def ingest(
        self, workspace_id: str, documents: list[SourceDocument]
    ) -> IngestResult:
        if not documents:
            raise ValueError("At least one document is required")
        dataset = self._dataset(workspace_id)
        payload = [document.as_knowledge_text() for document in documents]
        # One add + one cognify for the whole batch: never per document.
        await self._call("add", self._cognee.add(payload, dataset_name=dataset, node_set=[dataset]))
        await self._call("cognify", self._cognee.cognify(datasets=[dataset]))
        return IngestResult(workspace_id, len(documents), dataset)

    async def _call(self, name: str, coroutine):
        """Await one Cognee call under a timeout.

        Cognee has been observed to log "Pipeline run completed" and then never
        hand control back, which leaves the HTTP request open indefinitely. The
        bound turns that into a reportable failure, and the log lines identify
        which call stalled.
        """
        logger.info("cognee.%s started", name)
        try:
            result = await asyncio.wait_for(coroutine, timeout=self._timeout)
        except TimeoutError:
            logger.error("cognee.%s did not return within %ss", name, self._timeout)
            raise
        logger.info("cognee.%s returned", name)
        return result

    async def semantic_search(
        self, workspace_id: str, query: str, *, limit: int = 6
    ) -> list[RetrievedItem]:
        results = await self._cognee.search(
            query_text=query,
            query_type=self._cognee.SearchType.CHUNKS,
            datasets=[self._dataset(workspace_id)],
            top_k=limit,
        )
        return self._normalize(results, "semantic")

    async def graph_search(
        self, workspace_id: str, query: str, *, limit: int = 6
    ) -> list[RetrievedItem]:
        results = await self._cognee.search(
            query_text=query,
            query_type=self._cognee.SearchType.GRAPH_COMPLETION,
            datasets=[self._dataset(workspace_id)],
            top_k=limit,
            only_context=True,
        )
        return self._normalize(results, "graph")

    async def remember(self, workspace_id: str, session_id: str, content: str) -> None:
        await self._cognee.remember(
            content,
            dataset_name=self._dataset(workspace_id),
            session_id=self._session(workspace_id, session_id),
            self_improvement=False,
        )

    async def recall(
        self, workspace_id: str, session_id: str, query: str, *, limit: int = 4
    ) -> list[RetrievedItem]:
        # A workspace-prefixed session provides isolation for conversational memory.
        # With no query_type/datasets, Cognee checks this session cache first.
        results = await self._cognee.recall(
            query_text=query,
            session_id=self._session(workspace_id, session_id),
        )
        return self._normalize(results, "memory")[:limit]

    @classmethod
    def _normalize(cls, values: Any, retrieval_type: str) -> list[RetrievedItem]:
        if values is None:
            return []
        iterable: Iterable[Any] = (
            values if isinstance(values, (list, tuple)) else [values]
        )
        normalized: list[RetrievedItem] = []
        for value in iterable:
            dumped = cls._dump(value)
            text = cls._text(value, dumped)
            if text:
                metadata = dumped if isinstance(dumped, dict) else {}
                normalized.append(
                    RetrievedItem(
                        text=text,
                        retrieval_type=retrieval_type,
                        score=cls._score(metadata),
                        source=cls._source(metadata),
                        metadata=metadata,
                    )
                )
        return normalized

    @staticmethod
    def _dump(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return value
        if hasattr(value, "__dict__"):
            return vars(value)
        return value

    @staticmethod
    def _text(value: Any, dumped: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(dumped, dict):
            for key in ("text", "content", "answer", "result"):
                candidate = dumped.get(key)
                if candidate:
                    return str(candidate)
            return json.dumps(dumped, default=str)
        return str(dumped)

    @staticmethod
    def _score(metadata: dict[str, Any]) -> float | None:
        value = metadata.get("score")
        return float(value) if isinstance(value, (int, float)) else None

    @staticmethod
    def _source(metadata: dict[str, Any]) -> str | None:
        for key in ("source", "file_name", "document_name"):
            value = metadata.get(key)
            if value:
                return str(value)
        return None
