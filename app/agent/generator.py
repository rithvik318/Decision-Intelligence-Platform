from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.domain import RetrievalContext

SYSTEM_PROMPT = (
    "You are an analyst working inside an evidence-driven decision workspace. "
    "Answer strictly from the retrieved context. Cite supporting context items "
    "as [n]. If the context is insufficient, say so plainly and begin your "
    "answer with the token INSUFFICIENT_CONTEXT."
)

INSUFFICIENT = "INSUFFICIENT_CONTEXT"


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    answer: str
    needs_more_information: bool


class AnswerGenerator:
    """Thin OpenAI wrapper. Returns only the user-visible answer."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            if not self._settings.llm_api_key:
                raise RuntimeError(
                    "No LLM credentials: set OPENROUTER_API_KEY or OPENAI_API_KEY"
                )
            # OpenRouter is OpenAI-compatible, so only the base URL differs.
            self._client = AsyncOpenAI(
                api_key=self._settings.llm_api_key,
                base_url=self._settings.llm_base_url,
            )
        return self._client

    async def generate(
        self, question: str, context: RetrievalContext
    ) -> GeneratedAnswer:
        client = self._get_client()
        # Chat Completions is the surface both OpenAI and OpenRouter implement.
        response = await client.chat.completions.create(
            model=self._settings.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}\n\n"
                        f"Retrieved context:\n{context.as_prompt_block()}"
                    ),
                },
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        needs_more = text.startswith(INSUFFICIENT)
        if needs_more:
            text = text[len(INSUFFICIENT) :].strip(" :\n") or (
                "The workspace does not contain enough evidence to answer this yet."
            )
        return GeneratedAnswer(answer=text, needs_more_information=needs_more)
