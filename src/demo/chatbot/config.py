"""Runtime configuration.

Every secret comes from the environment (or a local, git-ignored ``.env``). There are no
fallback key values anywhere in the code base: a missing key disables the feature that
needs it, and production refuses to start without its mandatory secrets.
"""

from __future__ import annotations

import json
from datetime import date
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
MIN_SECRET_LEN = 32


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


def _split_list(value: Any) -> Any:
    """Accept JSON arrays or comma-separated strings (PowerShell-friendly)."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            return json.loads(text)
        return [item.strip() for item in text.split(",") if item.strip()]
    return value


StrList = Annotated[list[str], NoDecode]
DateList = Annotated[list[date], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- runtime -----------------------------------------------------------------------
    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    data_dir: Path = Path("./var")
    background_workers: bool = True
    seed_sample_data: bool = True

    # --- secrets (never defaulted) -----------------------------------------------------
    session_secret: SecretStr | None = None
    ledger_hmac_key: SecretStr | None = None
    admin_token: SecretStr | None = None
    webhook_signing_secret: SecretStr | None = None

    # --- Claude ------------------------------------------------------------------------
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    anthropic_max_tokens: int = Field(default=16000, ge=1024, le=64000)
    anthropic_timeout_s: float = Field(default=60.0, gt=0)
    anthropic_refusal_fallbacks: bool = True
    agent_max_iterations: int = Field(default=6, ge=1, le=12)
    agent_deadline_s: float = Field(default=90.0, gt=0)
    history_max_messages: int = Field(default=60, ge=6)

    # --- optional live-data integrations -------------------------------------------------
    nhtsa_enabled: bool = True
    nhtsa_vpic_base: str = "https://vpic.nhtsa.dot.gov/api"
    nhtsa_api_base: str = "https://api.nhtsa.gov"
    perplexity_api_key: SecretStr | None = None
    perplexity_model: str = "sonar"
    perplexity_api_url: str = "https://api.perplexity.ai/chat/completions"
    firecrawl_api_key: SecretStr | None = None
    firecrawl_api_url: str = "https://api.firecrawl.dev/v2/scrape"
    specials_urls: StrList = Field(default_factory=list)

    # --- CRM delivery (transactional outbox) -------------------------------------------
    crm_webhook_url: str | None = None
    crm_webhook_format: Literal["json", "adf"] = "json"
    outbox_max_attempts: int = Field(default=8, ge=1, le=50)
    outbox_poll_interval_s: float = Field(default=3.0, gt=0)

    # --- web / security ------------------------------------------------------------------
    cors_origins: StrList = Field(default_factory=list)
    frame_ancestors: StrList = Field(default_factory=list)
    client_ip_header: str | None = None
    max_body_bytes: int = Field(default=64 * 1024, ge=1024)
    max_message_chars: int = Field(default=2000, ge=50, le=20000)

    # --- rate limits ---------------------------------------------------------------------
    rate_limit_chat_per_minute: int = Field(default=20, ge=1)
    rate_limit_api_per_minute: int = Field(default=120, ge=1)
    rate_limit_lookup_per_hour: int = Field(default=20, ge=1)
    rate_limit_admin_per_minute: int = Field(default=240, ge=1)

    # --- retention -----------------------------------------------------------------------
    conversation_retention_days: int = Field(default=30, ge=1)
    analytics_retention_days: int = Field(default=400, ge=1)

    # --- dealership / scheduling ---------------------------------------------------------
    timezone: str = "America/Chicago"
    dealership_file: Path | None = None
    inventory_feed_path: Path | None = None
    service_records_seed_path: Path | None = None
    appointment_horizon_days: int = Field(default=30, ge=1, le=180)
    appointment_min_lead_minutes: int = Field(default=120, ge=0)
    appointment_max_active_per_phone: int = Field(default=3, ge=1)
    closed_dates: DateList = Field(default_factory=list)
    observe_default_holidays: bool = True

    @field_validator("specials_urls", "cors_origins", "frame_ancestors", "closed_dates", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> Any:
        return _split_list(value)

    @field_validator("specials_urls")
    @classmethod
    def _https_only(cls, value: list[str]) -> list[str]:
        for url in value:
            if not url.startswith("https://"):
                raise ValueError(f"specials URL must use https: {url}")
        return value

    @model_validator(mode="after")
    def _production_guard(self) -> Settings:
        if self.environment is not Environment.PRODUCTION:
            return self
        problems: list[str] = []
        for name in ("session_secret", "ledger_hmac_key", "admin_token"):
            secret = getattr(self, name)
            if secret is None or len(secret.get_secret_value()) < MIN_SECRET_LEN:
                problems.append(f"{name.upper()} must be set (>= {MIN_SECRET_LEN} chars)")
        if self.crm_webhook_url:
            if not self.crm_webhook_url.startswith("https://"):
                problems.append("CRM_WEBHOOK_URL must use https in production")
            secret = self.webhook_signing_secret
            if secret is None or len(secret.get_secret_value()) < MIN_SECRET_LEN:
                problems.append(f"WEBHOOK_SIGNING_SECRET must be set (>= {MIN_SECRET_LEN} chars)")
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self

    # --- derived -----------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def db_path(self) -> Path:
        return self.data_dir / "chatbot.sqlite3"

    @property
    def dealership_path(self) -> Path:
        return self.dealership_file or DATA_DIR / "dealership.json"

    @property
    def inventory_path(self) -> Path:
        return self.inventory_feed_path or DATA_DIR / "inventory_sample.json"

    @property
    def service_seed_path(self) -> Path:
        return self.service_records_seed_path or DATA_DIR / "service_records_sample.json"

    def integration_status(self) -> dict[str, bool]:
        """Which optional integrations are configured (never exposes values)."""
        return {
            "claude": self.anthropic_api_key is not None,
            "nhtsa": self.nhtsa_enabled,
            "perplexity": self.perplexity_api_key is not None,
            "firecrawl": self.firecrawl_api_key is not None and bool(self.specials_urls),
            "crm_webhook": bool(self.crm_webhook_url),
            "admin": self.admin_token is not None,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
