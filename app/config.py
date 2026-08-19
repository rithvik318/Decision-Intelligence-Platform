from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-oss-20b:free"


@dataclass(frozen=True, slots=True)
class Settings:
    openai_api_key: str | None = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY")
    )
    openai_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-5-mini")
    )
    openrouter_api_key: str | None = field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY")
    )
    openrouter_model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
    )
    github_token: str | None = field(default_factory=lambda: os.getenv("GITHUB_TOKEN"))
    # Upper bound on a single Cognee call. Cognee can stop returning control
    # after its pipeline has already logged completion, which would otherwise
    # hold the HTTP request open forever.
    cognee_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("COGNEE_TIMEOUT_SECONDS", "900"))
    )
    # Upper bound on a single LLM completion during decision analysis.
    llm_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("LLM_TIMEOUT_SECONDS", "180"))
    )
    # Graph enrichment is the only LLM-bound part of ingestion (two calls per
    # chunk). Off by default so an upload is fast and free; request it per
    # ingest, or flip this to make it the default.
    build_graph_on_ingest: bool = field(
        default_factory=lambda: os.getenv("COGNEE_BUILD_GRAPH_ON_INGEST", "").lower()
        in {"1", "true", "yes"}
    )
    # How many chunks Cognee enriches concurrently. Cognee's default is 2000,
    # which fires every chunk at once and gets a free-tier model rate-limited.
    cognee_chunks_per_batch: int = field(
        default_factory=lambda: int(os.getenv("COGNEE_CHUNKS_PER_BATCH", "4"))
    )
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("EDI_DATA_DIR", ".decision_intelligence")
        ).resolve()
    )

    @property
    def workspace_store_path(self) -> Path:
        return self.data_dir / "workspaces.json"

    @property
    def decision_store_path(self) -> Path:
        return self.data_dir / "decisions.json"

    # --- LLM provider boundary -------------------------------------------------
    # One place decides which provider the whole application talks to. Setting
    # OPENROUTER_API_KEY selects OpenRouter; otherwise OpenAI is used as before.

    @property
    def llm_provider(self) -> str:
        return "openrouter" if self.openrouter_api_key else "openai"

    @property
    def llm_api_key(self) -> str | None:
        return self.openrouter_api_key or self.openai_api_key

    @property
    def llm_model(self) -> str:
        """Model id in the provider's own namespace (no litellm route prefix)."""
        if self.llm_provider == "openrouter":
            return self.openrouter_model
        return self.openai_model

    @property
    def llm_base_url(self) -> str | None:
        """OpenAI-compatible base URL, or None to use the SDK default."""
        return OPENROUTER_BASE_URL if self.llm_provider == "openrouter" else None

    def configure_cognee_environment(self) -> None:
        """Point Cognee at local embedded storage and our LLM credentials.

        Cognee is configured through environment variables; we only fill in the
        values the operator has not set explicitly.

        OpenRouter is not one of Cognee's first-class providers, so it is wired
        through LLM_PROVIDER="custom", which routes to Cognee's GenericAPIAdapter
        and on to LiteLLM using the "openrouter/" model prefix plus LLM_ENDPOINT.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        defaults = {
            "DATA_ROOT_DIRECTORY": str(self.data_dir / "data"),
            "SYSTEM_ROOT_DIRECTORY": str(self.data_dir / "system"),
        }
        if self.llm_api_key:
            defaults["LLM_API_KEY"] = self.llm_api_key
        if self.llm_provider == "openrouter":
            defaults["LLM_PROVIDER"] = "custom"
            defaults["LLM_MODEL"] = f"openrouter/{self.llm_model}"
            defaults["LLM_ENDPOINT"] = OPENROUTER_BASE_URL
        else:
            defaults["LLM_MODEL"] = self.llm_model
        # OpenRouter serves no embeddings endpoint, so embeddings keep their own
        # provider. OpenAI stays the default; set EMBEDDING_PROVIDER (e.g.
        # "fastembed") to embed locally when no OpenAI quota is available.
        if self.openai_api_key:
            defaults["EMBEDDING_API_KEY"] = self.openai_api_key
        # Free-tier models rate-limit aggressively; Cognee's own limiter costs
        # nothing when the provider is generous and prevents a 429 storm when
        # it is not.
        defaults["LLM_RATE_LIMIT_ENABLED"] = "true"
        defaults["CHUNKS_PER_BATCH"] = str(self.cognee_chunks_per_batch)
        for key, value in defaults.items():
            os.environ.setdefault(key, value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
