"""Application settings, read from environment variables or a `.env` file.

Every value here can be overridden without touching code. See `.env.example`
at the repository root for the full list and what each one does.
"""

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    # The repo-root .env is shared by docker compose; backend/.env (if any) wins.
    model_config = SettingsConfigDict(env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"), extra="ignore")

    app_name: str = "Trolley Mate"
    environment: str = "development"
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'trolleymate.db').as_posix()}"
    # Signs login tokens. Leave unset to auto-generate one (see get_settings).
    secret_key: str = ""
    token_ttl_hours: int = 12
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    seed_on_startup: bool = True
    # Folder holding the built React app (`npm run build`). Served at / when present.
    frontend_dist: str = "../frontend/dist"

    # --- LLM provider -----------------------------------------------------
    # mock              offline, rule-based; no key needed (default, used by tests)
    # openai_compatible Campus Qwen proxy, OpenAI, Ollama, LM Studio, Groq, ...
    # anthropic         Claude via the official Anthropic SDK
    llm_provider: str = "mock"
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_timeout_s: float = 45.0
    llm_temperature: float = 0.2
    # Ask OpenAI-compatible servers for JSON mode. Turn off if the server rejects it.
    llm_json_mode: bool = True
    # Anthropic-specific
    anthropic_api_key: str = ""
    anthropic_effort: str = "low"
    anthropic_fallbacks: bool = True
    # If the real provider errors or returns invalid JSON, use the mock instead
    # of failing the request. Keeps the demo alive if the network drops.
    llm_fallback_to_mock: bool = True

    # --- Domain policy (owned by the AI Technical Manager) ----------------
    compliance_safety_threshold: float = 0.95
    max_corrections: int = 3
    price_max_age_hours: int = 24
    review_sla_minutes: int = 60
    solver_timeout_ms: int = 5000

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


_PLACEHOLDER_SECRETS = {"", "dev-secret-change-me", "change-me-to-a-long-random-string"}


def _local_secret() -> str:
    """A random signing key, generated once and kept in a git-ignored file so tokens
    survive restarts. Never a value anyone else could know."""
    path = BACKEND_DIR / ".secret_key"
    if path.exists() and path.read_text().strip():
        return path.read_text().strip()
    key = secrets.token_urlsafe(48)
    path.write_text(key)
    return key


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.secret_key.strip() in _PLACEHOLDER_SECRETS:
        settings.secret_key = _local_secret()
    return settings
