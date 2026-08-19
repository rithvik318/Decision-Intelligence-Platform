"""The provider boundary: which LLM the app and Cognee are pointed at."""

from __future__ import annotations

from app.config import DEFAULT_OPENROUTER_MODEL, OPENROUTER_BASE_URL, Settings


def _cognee_env(settings: Settings, monkeypatch) -> dict[str, str]:
    for key in (
        "LLM_API_KEY",
        "LLM_MODEL",
        "LLM_PROVIDER",
        "LLM_ENDPOINT",
        "EMBEDDING_API_KEY",
        "DATA_ROOT_DIRECTORY",
        "SYSTEM_ROOT_DIRECTORY",
    ):
        monkeypatch.delenv(key, raising=False)
    settings.configure_cognee_environment()
    import os

    return dict(os.environ)


def test_openai_remains_the_default_provider(tmp_path, monkeypatch) -> None:
    settings = Settings(
        openai_api_key="sk-openai",
        openai_model="gpt-5-mini",
        openrouter_api_key=None,
        data_dir=tmp_path,
    )
    assert settings.llm_provider == "openai"
    assert settings.llm_api_key == "sk-openai"
    assert settings.llm_model == "gpt-5-mini"
    assert settings.llm_base_url is None

    env = _cognee_env(settings, monkeypatch)
    assert env["LLM_MODEL"] == "gpt-5-mini"
    assert "LLM_PROVIDER" not in env
    assert "LLM_ENDPOINT" not in env


def test_openrouter_key_selects_openrouter(tmp_path, monkeypatch) -> None:
    settings = Settings(
        openai_api_key="sk-openai",
        openrouter_api_key="sk-or-v1-test",
        data_dir=tmp_path,
    )
    assert settings.llm_provider == "openrouter"
    assert settings.llm_api_key == "sk-or-v1-test"
    assert settings.llm_model == DEFAULT_OPENROUTER_MODEL
    assert settings.llm_base_url == OPENROUTER_BASE_URL

    env = _cognee_env(settings, monkeypatch)
    # Cognee has no first-class OpenRouter provider; "custom" routes through
    # its GenericAPIAdapter to LiteLLM, which needs the "openrouter/" prefix.
    assert env["LLM_PROVIDER"] == "custom"
    assert env["LLM_MODEL"] == f"openrouter/{DEFAULT_OPENROUTER_MODEL}"
    assert env["LLM_ENDPOINT"] == OPENROUTER_BASE_URL
    assert env["LLM_API_KEY"] == "sk-or-v1-test"
    # Embeddings are configured separately and stay on OpenAI by default.
    assert env["EMBEDDING_API_KEY"] == "sk-openai"


def test_operator_env_overrides_are_not_clobbered(tmp_path, monkeypatch) -> None:
    settings = Settings(openrouter_api_key="sk-or-v1-test", data_dir=tmp_path)
    monkeypatch.setenv("LLM_MODEL", "openrouter/meta-llama/llama-3.3-70b-instruct:free")
    settings.configure_cognee_environment()
    import os

    assert os.environ["LLM_MODEL"] == (
        "openrouter/meta-llama/llama-3.3-70b-instruct:free"
    )
