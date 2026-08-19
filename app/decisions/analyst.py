"""The LLM boundary for decision analysis.

One method per analysis stage, each returning a validated Pydantic model.
The model is asked for JSON and its reply is validated, never regex-parsed;
an invalid reply gets exactly one corrective retry before the stage fails.
Reuses the provider configuration from Settings — OpenRouter or OpenAI.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.decisions.models import (
    AlternativeSet,
    ClaimSet,
    EvidenceSet,
    RecommendationResult,
    RiskAssessment,
)
from app.domain import RetrievalContext

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

SYSTEM_PROMPT = (
    "You are a decision analyst. Work only from the supplied context; never "
    "invent facts. Cite context items by their [n] marker. Reply with a single "
    "JSON object matching the requested schema and nothing else — no prose, no "
    "markdown fences. Keep every field terse; give conclusions, not reasoning "
    "steps."
)


class DecisionAnalysisError(RuntimeError):
    """The LLM did not return usable structured output for a stage."""


class DecisionAnalyst:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            if not self._settings.llm_api_key:
                raise DecisionAnalysisError(
                    "No LLM credentials: set OPENROUTER_API_KEY or OPENAI_API_KEY"
                )
            self._client = AsyncOpenAI(
                api_key=self._settings.llm_api_key,
                base_url=self._settings.llm_base_url,
            )
        return self._client

    async def _structured(self, stage: str, instruction: str, schema: type[T]) -> T:
        prompt = (
            f"{instruction}\n\n"
            f"Return JSON matching this schema:\n"
            f"{json.dumps(schema.model_json_schema())}"
        )
        last_error = ""
        for attempt in (1, 2):
            content = await self._complete(stage, prompt, last_error)
            try:
                return schema.model_validate_json(_strip_fences(content))
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)[:600]
                logger.warning("%s: invalid structured output (attempt %s)", stage, attempt)
        raise DecisionAnalysisError(f"{stage} did not return valid JSON: {last_error}")

    async def _complete(self, stage: str, prompt: str, previous_error: str) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        if previous_error:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous reply did not validate against the schema:\n"
                        f"{previous_error}\nReply again with valid JSON only."
                    ),
                }
            )
        try:
            response = await asyncio.wait_for(
                self._get_client().chat.completions.create(
                    model=self._settings.llm_model,
                    messages=messages,
                    response_format={"type": "json_object"},
                ),
                timeout=self._settings.llm_timeout_seconds,
            )
        except TimeoutError as exc:
            raise DecisionAnalysisError(
                f"{stage} timed out after {self._settings.llm_timeout_seconds}s"
            ) from exc
        return response.choices[0].message.content or ""

    # --- analysis stages ----------------------------------------------------

    async def extract_evidence(
        self, question: str, context: RetrievalContext
    ) -> EvidenceSet:
        return await self._structured(
            "extract_evidence",
            f"Decision question: {question}\n\n"
            f"Context:\n{context.as_prompt_block()}\n\n"
            "Extract the discrete pieces of evidence that bear on the question. "
            "Give each a short evidence_id like E1, E2. Set `source` to the "
            "context item's source when shown. Skip anything irrelevant.",
            EvidenceSet,
        )

    async def generate_claims(self, question: str, evidence: str) -> ClaimSet:
        return await self._structured(
            "generate_claims",
            f"Decision question: {question}\n\nEvidence:\n{evidence}\n\n"
            "Derive the claims this evidence supports. Reference the "
            "evidence_ids that back each claim in supporting_evidence.",
            ClaimSet,
        )

    async def identify_assumptions_and_risks(
        self, question: str, evidence: str, claims: str
    ) -> RiskAssessment:
        return await self._structured(
            "identify_assumptions_and_risks",
            f"Decision question: {question}\n\nEvidence:\n{evidence}\n\n"
            f"Claims:\n{claims}\n\n"
            "List the unstated assumptions the claims rest on, and the risks of "
            "acting on them. Rate confidence and severity as low, medium or high.",
            RiskAssessment,
        )

    async def evaluate_alternatives(
        self, question: str, evidence: str, claims: str
    ) -> AlternativeSet:
        return await self._structured(
            "evaluate_alternatives",
            f"Decision question: {question}\n\nEvidence:\n{evidence}\n\n"
            f"Claims:\n{claims}\n\n"
            "Identify the realistic alternatives implied by the question and "
            "weigh each. Cite evidence_ids under `evidence`.",
            AlternativeSet,
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
        reassessment = (
            "\n\nPrevious decisions in this workspace:\n"
            f"{previous_decisions}\n"
            "This is a reassessment. Compare the current evidence against those "
            "decisions and list, in changed_since_previous, what has actually "
            "changed — evidence, assumptions or conclusions. Leave it empty if "
            "nothing material changed."
            if previous_decisions
            else ""
        )
        return await self._structured(
            "generate_recommendation",
            f"Decision question: {question}\n\nEvidence:\n{evidence}\n\n"
            f"Claims:\n{claims}\n\nAssumptions and risks:\n{assessment}\n\n"
            f"Alternatives:\n{alternatives}{reassessment}\n\n"
            "Recommend a course of action. The rationale must be two or three "
            "sentences grounded in the evidence, not a reasoning transcript.",
            RecommendationResult,
        )


def _strip_fences(content: str) -> str:
    """Tolerate a model that wraps its JSON in a markdown fence."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text.strip()
