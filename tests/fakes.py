"""Deterministic in-memory doubles: no network, no API key, no Cognee."""

from __future__ import annotations

from collections import defaultdict

from app.agent.generator import GeneratedAnswer
from app.decisions.models import (
    Alternative,
    AlternativeSet,
    Assumption,
    Claim,
    ClaimSet,
    Decision,
    Evidence,
    EvidenceSet,
    Level,
    Recommendation,
    RecommendationResult,
    Risk,
    RiskAssessment,
)
from app.domain import IngestResult, RetrievalContext, RetrievedItem, SourceDocument


def _tokens(text: str) -> set[str]:
    """Crude stems so the fake behaves a little like semantic search."""
    return {
        t.strip(".,;:()?!\"'").lower()[:6]
        for t in text.split()
        if len(t.strip(".,;:()?!\"'")) > 2
    }


class InMemoryKnowledgeFake:
    """Implements the KnowledgeService protocol with naive token overlap."""

    def __init__(self) -> None:
        self.documents: dict[str, list[SourceDocument]] = defaultdict(list)
        self.memories: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.decisions: dict[str, list[Decision]] = defaultdict(list)
        self.graphs_built: list[str] = []

    @staticmethod
    def _dataset(workspace_id: str) -> str:
        return f"workspace-{workspace_id.lower()}"

    async def ingest(
        self,
        workspace_id: str,
        documents: list[SourceDocument],
        *,
        build_graph: bool | None = None,
    ) -> IngestResult:
        if not documents:
            raise ValueError("At least one document is required")
        self.documents[workspace_id].extend(documents)
        if build_graph:
            await self.build_graph(workspace_id)
        return IngestResult(
            workspace_id,
            len(documents),
            self._dataset(workspace_id),
            graph_built=bool(build_graph),
        )

    async def build_graph(self, workspace_id: str) -> None:
        self.graphs_built.append(workspace_id)

    def _match(self, workspace_id: str, query: str) -> list[SourceDocument]:
        query_tokens = _tokens(query)
        scored = [
            (len(query_tokens & _tokens(doc.content)), doc)
            for doc in self.documents.get(workspace_id, [])
        ]
        return [doc for score, doc in sorted(scored, key=lambda p: -p[0]) if score]

    async def semantic_search(
        self, workspace_id: str, query: str, *, limit: int = 6
    ) -> list[RetrievedItem]:
        return [
            RetrievedItem(
                text=doc.content,
                retrieval_type="semantic",
                score=1.0,
                source=doc.file_name,
                metadata={"file_name": doc.file_name, "source": doc.source},
            )
            for doc in self._match(workspace_id, query)[:limit]
        ]

    async def graph_search(
        self, workspace_id: str, query: str, *, limit: int = 6
    ) -> list[RetrievedItem]:
        items: list[RetrievedItem] = []
        for doc in self._match(workspace_id, query)[:limit]:
            for line in doc.content.splitlines():
                if " depends on " in line or " competes with " in line:
                    items.append(
                        RetrievedItem(
                            text=line.strip(),
                            retrieval_type="graph",
                            source=doc.file_name,
                            metadata={"file_name": doc.file_name},
                        )
                    )
        return items[:limit]

    async def remember(
        self, workspace_id: str, session_id: str, content: str
    ) -> None:
        self.memories[(workspace_id, session_id)].append(content)

    async def recall(
        self, workspace_id: str, session_id: str, query: str, *, limit: int = 4
    ) -> list[RetrievedItem]:
        query_tokens = _tokens(query)
        return [
            RetrievedItem(text=memory, retrieval_type="memory", source="memory")
            for memory in self.memories.get((workspace_id, session_id), [])
            if query_tokens & _tokens(memory)
        ][:limit]


    # --- decision memory ----------------------------------------------------

    async def store_decision(
        self, workspace_id: str, session_id: str, decision: Decision
    ) -> None:
        self.decisions[workspace_id].append(decision)
        # Mirrors the real adapter: the summary also lands in session memory.
        self.memories[(workspace_id, session_id)].append(decision.as_memory_text())

    async def load_decisions(
        self, workspace_id: str, *, limit: int = 5
    ) -> list[Decision]:
        return list(reversed(self.decisions.get(workspace_id, [])))[:limit]


class FakeDecisionAnalyst:
    """Deterministic stand-in for the LLM: derives output from the context."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.previous_seen: list[str] = []

    async def extract_evidence(self, question: str, context) -> EvidenceSet:
        self.calls.append("extract_evidence")
        return EvidenceSet(
            evidence=[
                Evidence(
                    evidence_id=f"E{index}",
                    statement=item.text.strip()[:120],
                    source=item.source,
                    relevance=Level.HIGH,
                )
                for index, item in enumerate(context.items[:4], start=1)
            ]
        )

    async def generate_claims(self, question: str, evidence: str) -> ClaimSet:
        self.calls.append("generate_claims")
        ids = [line.split(":", 1)[0] for line in evidence.splitlines() if ":" in line]
        return ClaimSet(
            claims=[Claim(statement=f"Claim from {i}", supporting_evidence=[i]) for i in ids]
        )

    async def identify_assumptions_and_risks(
        self, question: str, evidence: str, claims: str
    ) -> RiskAssessment:
        self.calls.append("identify_assumptions_and_risks")
        return RiskAssessment(
            assumptions=[
                Assumption(statement="Current conditions persist", confidence=Level.MEDIUM)
            ],
            risks=[
                Risk(
                    statement="Grid capacity is constrained",
                    severity=Level.HIGH,
                    rationale="Repeatedly cited in the evidence",
                )
            ],
        )

    async def evaluate_alternatives(
        self, question: str, evidence: str, claims: str
    ) -> AlternativeSet:
        self.calls.append("evaluate_alternatives")
        return AlternativeSet(
            alternatives=[
                Alternative(
                    name="Residential",
                    description="Rooftop residential focus",
                    advantages=["Larger installed base"],
                    disadvantages=["Declining tariffs"],
                    evidence=["E1"],
                ),
                Alternative(
                    name="Commercial",
                    description="Commercial rooftop focus",
                    advantages=["In-house EPC leverage"],
                    disadvantages=["Price compression"],
                    evidence=["E2"],
                ),
            ]
        )

    async def generate_recommendation(
        self,
        question: str,
        evidence: str,
        claims: str,
        assessment: str,
        alternatives: str,
        previous_decisions: str,
    ) -> RecommendationResult:
        self.calls.append("generate_recommendation")
        self.previous_seen.append(previous_decisions)
        changed = ["Grid constraint is now rated high"] if previous_decisions else []
        return RecommendationResult(
            recommendation=Recommendation(
                statement="Prioritise commercial rooftop",
                rationale="Commercial leverages the in-house EPC team.",
                confidence=Level.MEDIUM,
            ),
            changed_since_previous=changed,
        )


class EchoGenerator:
    """Answers by quoting retrieved context, so assertions stay deterministic."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate(
        self, question: str, context: RetrievalContext
    ) -> GeneratedAnswer:
        self.calls.append(question)
        if not context.items:
            return GeneratedAnswer(
                answer="No evidence in this workspace yet.",
                needs_more_information=True,
            )
        quoted = " ".join(
            f"[{index}] {item.text.strip()[:160]}"
            for index, item in enumerate(context.items[:3], start=1)
        )
        return GeneratedAnswer(
            answer=f"Based on workspace evidence: {quoted}",
            needs_more_information=False,
        )
