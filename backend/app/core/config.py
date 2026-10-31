"""Application settings, read from environment variables or a `.env` file.

Every value here can be overridden without touching code. See `.env.example`
at the repository root for the full list and what each one does.
"""

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    # The repo-root .env is shared by docker compose; backend/.env (if any) wins.
    model_config = SettingsConfigDict(env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"), extra="ignore")

    tracing_enabled: bool = False
    tracing_endpoint: str = "http://127.0.0.1:4318/v1/traces"
    tracing_sample_ratio: float = Field(default=1.0, ge=0, le=1)
    app_name: str = "Trolley Mate"
    environment: str = "development"
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'trolleymate.db').as_posix()}"
    # Keys rate-limit identifiers. Leave unset to auto-generate one (see get_settings).
    secret_key: str = ""
    token_ttl_hours: int = Field(default=8, ge=1, le=168)
    session_idle_minutes: int = Field(default=30, ge=1, le=1440)
    max_active_sessions: int = Field(default=3, ge=1, le=20)
    api_requests_per_minute: int = Field(default=300, ge=1)
    account_writes_per_minute: int = Field(default=30, ge=1)
    auth_attempts_per_minute: int = Field(default=10, ge=1)
    account_login_attempts_per_quarter_hour: int = Field(default=10, ge=1)
    registrations_per_hour: int = Field(default=5, ge=1)
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
    # Rate limits (HTTP 429/503): retry this many times, but only if the server asks us to wait
    # no longer than llm_retry_max_wait_s; otherwise fall back to the offline mock straight away.
    llm_max_retries: int = 2
    llm_retry_max_wait_s: float = 8.0
    llm_temperature: float = 0.2
    llm_max_output_tokens: int = Field(default=768, ge=1, le=16384)
    # Empty uses the provider default, except Groq Qwen uses instruct mode.
    llm_reasoning_effort: str = ""
    # Ask OpenAI-compatible servers for JSON mode. Turn off if the server rejects it.
    llm_json_mode: bool = True
    # Live retailer/partner price feed for `partner_api` retailers (GET {url}/prices?retailer=&sku=).
    # Empty means the demo's simulated feed is used, and those quotes are labelled synthetic.
    partner_api_url: str = ""
    partner_api_key: str = ""
    partner_api_timeout_s: float = 3.0
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
    # The seeded 8-week price history is generated for the demo, not observed at a retailer, so buy-timing
    # advice built on it is labelled as demo data (1.2.6). Set false once real recorded history is imported.
    demo_price_history: bool = True

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
