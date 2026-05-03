from __future__ import annotations

from config import Settings


def test_settings_from_env_uses_defaults_without_env(monkeypatch) -> None:
    for name in (
        "GITHUB_TOKEN",
        "GITHUB_WEBHOOK_SECRET",
        "HF_API_TOKEN",
        "HUGGINGFACE_API_TOKEN",
        "HF_MODEL_ID",
        "HF_API_BASE_URL",
        "MAX_REVIEW_CHUNKS",
        "MAX_TOKENS_PER_CHUNK",
        "MAX_AGENT_CONCURRENCY",
        "AGENT_TIMEOUT_SECONDS",
        "AGENT_MAX_RETRIES",
        "COST_PER_1K_TOKENS",
        "POST_GITHUB_COMMENT",
        "MOCK_AI",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.hf_model_id == "google/gemma-3-1b-it"
    assert settings.hf_api_url == "https://api-inference.huggingface.co/models/google/gemma-3-1b-it"
    assert settings.max_review_chunks == 50
    assert not settings.mock_ai


def test_settings_from_env_parses_overrides(monkeypatch) -> None:
    monkeypatch.setenv("MOCK_AI", "true")
    monkeypatch.setenv("POST_GITHUB_COMMENT", "false")
    monkeypatch.setenv("MAX_REVIEW_CHUNKS", "12")
    monkeypatch.setenv("HF_API_BASE_URL", "https://example.test/models/")

    settings = Settings.from_env()

    assert settings.mock_ai
    assert not settings.post_github_comment
    assert settings.max_review_chunks == 12
    assert settings.hf_api_url == "https://example.test/models/google/gemma-3-1b-it"
