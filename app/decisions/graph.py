"""The decision lifecycle as a LangGraph workflow.

One node per stage, typed state, and a single bounded retrieval refinement.
Only structured outputs are carried in state — no reasoning traces.
"""

from __future__ import annotations

import logging
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.decisions.analyst import DecisionAnalyst
from app.decisions.models import (
    Alternative,
    Assumption,
    Claim,
    Decision,
    DecisionStatus,
    Evidence,
    Recommendation,
    Risk,
)
from app.domain import KnowledgeService, RetrievalContext, RetrievedItem
from app.retrieval import WorkspaceRetriever

logger = logging.getLogger(__name__)

MAX_RETRIEVAL_ATTEMPTS = 2
MIN_CONTEXT_ITEMS = 2
PREVIOUS_DECISION_LIMIT = 3

# A reassessment is a request to revisit earlier conclusions. Detected by
# keyword rather than by an LLM call: deterministic, free, and testable.
REASSESSMENT_MARKERS = (
    "reassess",
    "re-assess",
    "revisit",
    "previous decision",
    "earlier decision",
    "last decision",
    "still valid",
    "still hold",
    "update our decision",
    "change our mind",
)


class DecisionState(TypedDict, total=False):
    question: str
    workspace_id: str
    session_id: str
    retrieval_query: str
    is_reassessment: bool
    reassess_decision_id: str
    attempts: int
    context: RetrievalContext
    previous_decisions: list[Decision]
    evidence: list[Evidence]
    claims: list[Claim]
    assumptions: list[Assumption]
    risks: list[Risk]
    alternatives: list[Alternative]
    recommendation: Recommendation
    changed_since_previous: list[str]
    decision: Decision


class DecisionAgent:
    """LangGraph workflow: question in, persisted Decision out."""

    def __init__(
        self,
        retriever: WorkspaceRetriever,
        knowledge: KnowledgeService,
        analyst: DecisionAnalyst,
    ) -> None:
        self._retriever = retriever
        self._knowledge = knowledge
        self._analyst = analyst

        builder = StateGraph(DecisionState)
        builder.add_node("understand_decision", self._understand_decision)
        builder.add_node("retrieve_context", self._retrieve_context)
        builder.add_node("refine_retrieval", self._refine_retrieval)
        builder.add_node("retrieve_previous_decisions", self._retrieve_previous_decisions)
        builder.add_node("extract_evidence", self._extract_evidence)
        builder.add_node("generate_claims", self._generate_claims)
        builder.add_node("identify_assumptions_and_risks", self._identify_assumptions_and_risks)
        builder.add_node("evaluate_alternatives", self._evaluate_alternatives)
        builder.add_node("generate_recommendation", self._generate_recommendation)
        builder.add_node("persist_decision", self._persist_decision)
        builder.add_node("respond", self._respond)

        builder.add_edge(START, "understand_decision")
        builder.add_edge("understand_decision", "retrieve_context")
        builder.add_conditional_edges(
            "retrieve_context",
            self._route_after_retrieval,
            {"refine": "refine_retrieval", "continue": "retrieve_previous_decisions"},
        )
        builder.add_edge("refine_retrieval", "retrieve_context")
        builder.add_edge("retrieve_previous_decisions", "extract_evidence")
        builder.add_edge("extract_evidence", "generate_claims")
        builder.add_edge("generate_claims", "identify_assumptions_and_risks")
        builder.add_edge("identify_assumptions_and_risks", "evaluate_alternatives")
        builder.add_edge("evaluate_alternatives", "generate_recommendation")
        builder.add_edge("generate_recommendation", "persist_decision")
        builder.add_edge("persist_decision", "respond")
        builder.add_edge("respond", END)

        self.graph = builder.compile(checkpointer=InMemorySaver())

    async def run(
        self,
        question: str,
        workspace_id: str,
        session_id: str,
        reassess_decision_id: str | None = None,
    ) -> Decision:
        """Run the workflow. `reassess_decision_id` names the decision being
        revisited, making a reassessment explicit instead of inferred from the
        question wording."""
        state = await self.graph.ainvoke(
            {
                "question": question,
                "workspace_id": workspace_id,
                "session_id": session_id,
                "reassess_decision_id": reassess_decision_id or "",
                "attempts": 0,
            },
            {"configurable": {"thread_id": f"decision:{workspace_id}:{session_id}"}},
        )
        return state["decision"]

    # --- nodes --------------------------------------------------------------

    async def _understand_decision(self, state: DecisionState) -> dict:
        question = state["question"].strip()
        if not question:
            raise ValueError("question must not be empty")
        lowered = question.lower()
        # An explicitly targeted decision settles it; otherwise fall back to the
        # Phase 2 wording heuristic.
        is_reassessment = bool(state.get("reassess_decision_id")) or any(
            marker in lowered for marker in REASSESSMENT_MARKERS
        )
        return {"retrieval_query": question, "is_reassessment": is_reassessment}

    async def _retrieve_context(self, state: DecisionState) -> dict:
        context = await self._retriever.retrieve_context(
            state["workspace_id"], state["session_id"], state["retrieval_query"]
        )
        return {"context": context, "attempts": state.get("attempts", 0) + 1}

    @staticmethod
    def _route_after_retrieval(state: DecisionState) -> str:
        context = state.get("context")
        thin = context is None or len(context.items) < MIN_CONTEXT_ITEMS
        if thin and state.get("attempts", 0) < MAX_RETRIEVAL_ATTEMPTS:
            return "refine"
        return "continue"

    async def _refine_retrieval(self, state: DecisionState) -> dict:
        return {
            "retrieval_query": (
                "Background, key entities, trade-offs, risks and constraints "
                f"relevant to: {state['question']}"
            )
        }

    async def _retrieve_previous_decisions(self, state: DecisionState) -> dict:
        previous = list(
            await self._knowledge.load_decisions(
                state["workspace_id"], limit=PREVIOUS_DECISION_LIMIT
            )
        )
        # When a specific decision is being reassessed it leads the list, so the
        # existing persist step links `supersedes` to it rather than to whatever
        # happens to be newest.
        target_id = state.get("reassess_decision_id")
        if target_id:
            target = next(
                (d for d in previous if d.decision_id == target_id), None
            )
            if target is None:
                target = await self._knowledge.get_decision(
                    state["workspace_id"], target_id
                )
            if target is not None:
                previous = [target] + [
                    d for d in previous if d.decision_id != target_id
                ]
        return {"previous_decisions": previous}

    async def _extract_evidence(self, state: DecisionState) -> dict:
        result = await self._analyst.extract_evidence(
            state["question"], state["context"]
        )
        return {"evidence": list(result.evidence)}

    async def _generate_claims(self, state: DecisionState) -> dict:
        result = await self._analyst.generate_claims(
            state["question"], _render_evidence(state.get("evidence", []))
        )
        return {"claims": list(result.claims)}

    async def _identify_assumptions_and_risks(self, state: DecisionState) -> dict:
        result = await self._analyst.identify_assumptions_and_risks(
            state["question"],
            _render_evidence(state.get("evidence", [])),
            _render_claims(state.get("claims", [])),
        )
        return {
            "assumptions": list(result.assumptions),
            "risks": list(result.risks),
        }

    async def _evaluate_alternatives(self, state: DecisionState) -> dict:
        result = await self._analyst.evaluate_alternatives(
            state["question"],
            _render_evidence(state.get("evidence", [])),
            _render_claims(state.get("claims", [])),
        )
        return {"alternatives": list(result.alternatives)}

    async def _generate_recommendation(self, state: DecisionState) -> dict:
        previous = state.get("previous_decisions") or []
        # Prior decisions only enter the prompt for an explicit reassessment,
        # so a fresh question is not anchored to an earlier conclusion.
        previous_block = (
            "\n".join(d.as_previous_context() for d in previous)
            if state.get("is_reassessment") and previous
            else ""
        )
        result = await self._analyst.generate_recommendation(
            state["question"],
            _render_evidence(state.get("evidence", [])),
            _render_claims(state.get("claims", [])),
            _render_assessment(state.get("assumptions", []), state.get("risks", [])),
            _render_alternatives(state.get("alternatives", [])),
            previous_block,
        )
        return {
            "recommendation": result.recommendation,
            "changed_since_previous": list(result.changed_since_previous),
        }

    async def _persist_decision(self, state: DecisionState) -> dict:
        previous = state.get("previous_decisions") or []
        is_reassessment = bool(state.get("is_reassessment") and previous)
        decision = Decision(
            workspace_id=state["workspace_id"],
            session_id=state["session_id"],
            question=state["question"],
            status=(
                DecisionStatus.REASSESSED if is_reassessment else DecisionStatus.PROPOSED
            ),
            recommendation=state["recommendation"],
            evidence=state.get("evidence", []),
            claims=state.get("claims", []),
            assumptions=state.get("assumptions", []),
            risks=state.get("risks", []),
            alternatives=state.get("alternatives", []),
            sources=_sources(state["context"].items),
            supersedes=previous[0].decision_id if is_reassessment else None,
            changed_since_previous=(
                state.get("changed_since_previous", []) if is_reassessment else []
            ),
        )
        await self._knowledge.store_decision(
            state["workspace_id"], state["session_id"], decision
        )
        return {"decision": decision}

    async def _respond(self, state: DecisionState) -> dict:
        logger.info(
            "decision %s recorded for workspace %s",
            state["decision"].decision_id,
            state["workspace_id"],
        )
        return {}


# --- prompt rendering helpers ----------------------------------------------


def _render_evidence(items: list[Evidence]) -> str:
    return (
        "\n".join(
            f"{e.evidence_id}: {e.statement}"
            + (f" (source: {e.source})" if e.source else "")
            for e in items
        )
        or "(none)"
    )


def _render_claims(items: list[Claim]) -> str:
    return (
        "\n".join(
            f"- {c.statement} [{', '.join(c.supporting_evidence) or 'unsupported'}]"
            for c in items
        )
        or "(none)"
    )


def _render_assessment(assumptions: list[Assumption], risks: list[Risk]) -> str:
    lines = [f"- assumption ({a.confidence.value}): {a.statement}" for a in assumptions]
    lines += [f"- risk ({r.severity.value}): {r.statement}" for r in risks]
    return "\n".join(lines) or "(none)"


def _render_alternatives(items: list[Alternative]) -> str:
    return (
        "\n".join(
            f"- {a.name}: {a.description} | pros: {'; '.join(a.advantages) or 'none'}"
            f" | cons: {'; '.join(a.disadvantages) or 'none'}"
            for a in items
        )
        or "(none)"
    )


def _sources(items: tuple[RetrievedItem, ...]) -> list[str]:
    sources: list[str] = []
    for item in items:
        source = item.source or item.metadata.get("file_name")
        if source and str(source) not in sources:
            sources.append(str(source))
    return sources
