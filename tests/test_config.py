from __future__ import annotations

from app.config import Settings


def test_settings_from_env_uses_defaults_without_env(monkeypatch) -> None:
    monkeypatch.setattr("app.config.load_dotenv", lambda: None)
    for name in (
        "GITHUB_TOKEN",
        "GITHUB_WEBHOOK_SECRET",
        "GITHUB_APP_ID",
        "GITHUB_APP_PRIVATE_KEY",
        "GITHUB_APP_PRIVATE_KEY_PATH",
        "GITHUB_APP_INSTALLATION_ID",
        "HF_API_TOKEN",
        "HUGGINGFACE_API_TOKEN",
        "GROQ_API_KEY",
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

    assert settings.hf_model_id == "llama-3.3-70b-versatile"
    assert settings.hf_api_url == "https://api.groq.com/openai/v1/chat/completions"
    assert settings.max_review_chunks == 50
    assert not settings.github_configured
    assert not settings.github_app_configured
    assert not settings.mock_ai


def test_settings_from_env_parses_overrides(monkeypatch) -> None:
    monkeypatch.setattr("app.config.load_dotenv", lambda: None)
    monkeypatch.setenv("MOCK_AI", "true")
    monkeypatch.setenv("POST_GITHUB_COMMENT", "false")
    monkeypatch.setenv("MAX_REVIEW_CHUNKS", "12")
    monkeypatch.setenv("HF_MODEL_ID", "custom-model")
    monkeypatch.setenv("HF_API_BASE_URL", "https://example.test/models/")
    monkeypatch.setenv("GITHUB_APP_ID", "123")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", "/tmp/app.pem")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "456")

    settings = Settings.from_env()

    assert settings.mock_ai
    assert not settings.post_github_comment
    assert settings.max_review_chunks == 12
    assert settings.hf_api_url == "https://example.test/models/chat/completions"
    assert settings.hf_model_id == "custom-model"
    assert settings.github_app_id == 123
    assert settings.github_app_private_key_path == "/tmp/app.pem"
    assert settings.github_app_installation_id == 456
    assert settings.github_app_configured
    assert settings.github_configured
