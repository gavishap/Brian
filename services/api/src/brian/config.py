"""Runtime configuration, read from environment variables (and a local `.env` file)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"

    # --- Database (Supabase Postgres; use the pooler / direct connection string) -------------
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres",
        description="SQLAlchemy URL. Plain postgres:// URLs are converted to asyncpg.",
    )
    database_pool_size: int = 5

    # --- Supabase Auth ----------------------------------------------------------------------
    supabase_url: str = "http://127.0.0.1:54321"
    # Legacy HS256 projects: set the JWT secret. Projects on asymmetric signing keys leave this
    # empty and tokens are verified against the project's JWKS endpoint.
    supabase_jwt_secret: SecretStr | None = None
    supabase_jwt_audience: str = "authenticated"
    # Optional: lets `DELETE /v1/me` remove the auth user too (App Store account-deletion rule).
    supabase_service_role_key: SecretStr | None = None

    # --- Claude -----------------------------------------------------------------------------
    # The Anthropic SDK reads ANTHROPIC_API_KEY itself. With llm_enabled=false (or no key) the
    # nudge copywriter falls back to templates and chat returns a friendly error.
    llm_enabled: bool = True
    coach_model: str = "claude-opus-5-5"
    coach_effort: Effort = "medium"
    coach_max_tokens: int = 32000
    coach_max_iterations: int = 8
    copy_model: str = "claude-opus-5-5"
    copy_effort: Effort = "low"
    reflection_model: str = "claude-opus-5-5"
    reflection_effort: Effort = "high"
    # Server-side refusal fallbacks (re-runs a declined request on Anthropic's recommended model).
    llm_refusal_fallbacks: bool = True
    chat_daily_message_limit: int = 200

    # --- Push (Expo push service) -------------------------------------------------------------
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"
    expo_receipts_url: str = "https://exp.host/--/api/v2/push/getReceipts"
    expo_access_token: SecretStr | None = None
    push_dry_run: bool = False

    # --- Nudge engine -----------------------------------------------------------------------
    policy_version: str = "ts-factorized-v1"
    policy_prior_strength: float = 4.0
    policy_epsilon: float = 0.1
    policy_user_half_life_days: float = 45.0
    policy_global_half_life_days: float = 90.0
    nudge_attribution_hours: float = 3.0
    nudge_min_gap_minutes: int = 150
    planning_horizon_hours: int = 30

    # --- Internal endpoints (cron-style tick for serverless deployments) ----------------------
    internal_api_key: SecretStr | None = None

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix) :]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
