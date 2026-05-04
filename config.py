from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    github_token: str | None = None
    github_webhook_secret: str | None = None
    github_app_id: str | None = None
    github_app_private_key_path: str | None = None
    github_app_installation_id: str | None = None
    api_token: str | None = None
    model_id: str = "llama-3.3-70b-versatile"
    api_base_url: str = "https://api.groq.com/openai/v1"
    synthesizer_model_id: str | None = None
    max_review_chunks: int = 50
    max_tokens_per_chunk: int = 2000
    max_agent_concurrency: int = 6
    agent_timeout_seconds: int = 60
    agent_max_retries: int = 3
    cost_per_1k_tokens: float = 0.0001
    post_github_comment: bool = True
    mock_ai: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        defaults = cls()
        return cls(
            github_token=os.getenv("GITHUB_TOKEN") or None,
            github_webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET") or None,
            github_app_id=os.getenv("GITHUB_APP_ID") or None,
            github_app_private_key_path=os.getenv("GITHUB_APP_PRIVATE_KEY_PATH") or None,
            github_app_installation_id=os.getenv("GITHUB_APP_INSTALLATION_ID") or None,
            api_token=os.getenv("API_TOKEN") or os.getenv("GROQ_API_KEY") or os.getenv("HF_API_TOKEN") or os.getenv("HUGGINGFACE_API_TOKEN") or None,
            model_id=os.getenv("MODEL_ID") or os.getenv("HF_MODEL_ID", defaults.model_id),
            api_base_url=(os.getenv("API_BASE_URL") or os.getenv("HF_API_BASE_URL", defaults.api_base_url)).rstrip("/"),
            synthesizer_model_id=os.getenv("SYNTHESIZER_MODEL_ID") or None,
            max_review_chunks=_env_int("MAX_REVIEW_CHUNKS", defaults.max_review_chunks),
            max_tokens_per_chunk=_env_int("MAX_TOKENS_PER_CHUNK", defaults.max_tokens_per_chunk),
            max_agent_concurrency=_env_int("MAX_AGENT_CONCURRENCY", defaults.max_agent_concurrency),
            agent_timeout_seconds=_env_int("AGENT_TIMEOUT_SECONDS", defaults.agent_timeout_seconds),
            agent_max_retries=_env_int("AGENT_MAX_RETRIES", defaults.agent_max_retries),
            cost_per_1k_tokens=_env_float("COST_PER_1K_TOKENS", defaults.cost_per_1k_tokens),
            post_github_comment=_env_bool("POST_GITHUB_COMMENT", defaults.post_github_comment),
            mock_ai=_env_bool("MOCK_AI", defaults.mock_ai),
        )

    @property
    def api_url(self) -> str:
        return f"{self.api_base_url}/chat/completions"

    @property
    def github_app_configured(self) -> bool:
        return bool(
            self.github_app_id
            and self.github_app_private_key_path
            and self.github_app_installation_id
        )

    @property
    def github_configured(self) -> bool:
        return self.github_app_configured or bool(self.github_token)

    @property
    def api_configured(self) -> bool:
        return bool(self.api_token) or self.mock_ai
