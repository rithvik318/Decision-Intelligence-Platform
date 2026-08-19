from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.generator import AnswerGenerator
from app.domain import KnowledgeService, RetrievalContext, RetrievedItem
from app.retrieval import WorkspaceRetriever


class AgentState(TypedDict, total=False):
    user_query: str
    workspace_id: str
    session_id: str
    retrieval_query: str
    plan_summary: str
    context: RetrievalContext
    answer: str
    final_response: str
    attempts: int
    needs_more_information: bool


@dataclass(frozen=True, slots=True)
class AgentResult:
    answer: str
    sources: tuple[str, ...]
    semantic_hits: int
    graph_hits: int
    memory_hits: int


class WorkspaceAgent:
    """Minimal stateful LangGraph workflow over a workspace.

    Phase 1 shape: understand -> retrieve -> reason -> (one refinement) ->
    respond -> persist memory. The full decision lifecycle extends this graph."""

    def __init__(
        self,
        retriever: WorkspaceRetriever,
        knowledge: KnowledgeService,
        generator: AnswerGenerator,
    ) -> None:
        self._retriever = retriever
        self._knowledge = knowledge
        self._generator = generator
        builder = StateGraph(AgentState)
        builder.add_node("understand", self._understand)
        builder.add_node("retrieve", self._retrieve)
        builder.add_node("reason", self._reason)
        builder.add_node("refine", self._refine)
        builder.add_node("respond", self._respond)
        builder.add_node("update_memory", self._update_memory)
        builder.add_edge(START, "understand")
        builder.add_edge("understand", "retrieve")
        builder.add_edge("retrieve", "reason")
        builder.add_conditional_edges(
            "reason",
            self._route_after_reason,
            {"retry": "refine", "respond": "respond"},
        )
        builder.add_edge("refine", "retrieve")
        builder.add_edge("respond", "update_memory")
        builder.add_edge("update_memory", END)
        self.graph = builder.compile(checkpointer=InMemorySaver())

    async def run(self, message: str, workspace_id: str, session_id: str) -> AgentResult:
        state = await self.graph.ainvoke(
            {
                "user_query": message,
                "workspace_id": workspace_id,
                "session_id": session_id,
                "attempts": 0,
            },
            {"configurable": {"thread_id": f"{workspace_id}:{session_id}"}},
        )
        context = state["context"]
        return AgentResult(
            answer=state["final_response"],
            sources=self._sources(context.items),
            semantic_hits=len(context.semantic),
            graph_hits=len(context.graph),
            memory_hits=len(context.memories),
        )

    async def _understand(self, state: AgentState) -> dict:
        query = state["user_query"].strip()
        if not query:
            raise ValueError("message must not be empty")
        return {
            "retrieval_query": query,
            "plan_summary": "Retrieve workspace evidence, relationships, and relevant memory.",
        }

    async def _retrieve(self, state: AgentState) -> dict:
        context = await self._retriever.retrieve_context(
            state["workspace_id"], state["session_id"], state["retrieval_query"]
        )
        return {"context": context, "attempts": state.get("attempts", 0) + 1}

    async def _reason(self, state: AgentState) -> dict:
        draft = await self._generator.generate(state["user_query"], state["context"])
        return {
            "answer": draft.answer,
            "needs_more_information": draft.needs_more_information,
        }

    @staticmethod
    def _route_after_reason(state: AgentState) -> str:
        if state.get("needs_more_information") and state.get("attempts", 0) < 2:
            return "retry"
        return "respond"

    async def _refine(self, state: AgentState) -> dict:
        return {
            "retrieval_query": (
                f"Background, key entities, and evidence relevant to: "
                f"{state['user_query']}"
            )
        }

    async def _respond(self, state: AgentState) -> dict:
        return {"final_response": state["answer"]}

    async def _update_memory(self, state: AgentState) -> dict:
        # Persist only the user-visible interaction, never private model reasoning.
        memory = f"Question: {state['user_query']}\nAnswer: {state['final_response']}"
        await self._knowledge.remember(state["workspace_id"], state["session_id"], memory)
        return {}

    @staticmethod
    def _sources(items: tuple[RetrievedItem, ...]) -> tuple[str, ...]:
        sources: list[str] = []
        for item in items:
            source = item.source or item.metadata.get("file_name")
            if source and str(source) not in sources:
                sources.append(str(source))
        return tuple(sources)
