"""ClawBridge configuration management.

Loads settings from .env file and environment variables.
BYOK keys stay in memory only -- never logged, never written to disk beyond .env.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

from clawbridge.shared.schemas import EngineName, PolicyMode


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    # ── Server ────────────────────────────────────────────────────────────
    host: str = Field(default="127.0.0.1", alias="CLAWBRIDGE_HOST")
    port: int = Field(default=8765, alias="CLAWBRIDGE_PORT")

    # ── BYOK Keys (never logged) ─────────────────────────────────────────
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    default_model: str = Field(default="claude-3-5-sonnet-20241022", alias="DEFAULT_MODEL")

    # ── Engines ───────────────────────────────────────────────────────────
    enabled_engines: str = Field(default="browser_use,openclaw", alias="ENABLED_ENGINES")
    openclaw_path: str = Field(default="", alias="OPENCLAW_PATH")

    # ── Browser ───────────────────────────────────────────────────────────
    browser_headless: bool = Field(default=True, alias="BROWSER_HEADLESS")

    # ── Policy ────────────────────────────────────────────────────────────
    policy_mode: PolicyMode = Field(default=PolicyMode.GUARDED, alias="POLICY_MODE")
    max_concurrent_tasks: int = Field(default=3, alias="MAX_CONCURRENT_TASKS")
    max_actions_per_task: int = Field(default=50, alias="MAX_ACTIONS_PER_TASK")

    # ── Telemetry ─────────────────────────────────────────────────────────
    log_retention_hours: int = Field(default=72, alias="LOG_RETENTION_HOURS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ── Database ──────────────────────────────────────────────────────────
    db_path: str = Field(default="clawbridge.db", alias="CLAWBRIDGE_DB")

    # ── Remote Bridge ─────────────────────────────────────────────────────
    remote_bridge_url: str = Field(default="", alias="REMOTE_BRIDGE_URL")
    remote_auth_token: str = Field(default="", alias="REMOTE_AUTH_TOKEN")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def enabled_engine_list(self) -> list[EngineName]:
        """Parse enabled engines from comma-separated string."""
        engines = []
        for name in self.enabled_engines.split(","):
            name = name.strip().lower()
            if name in EngineName.__members__.values():
                engines.append(EngineName(name))
        return engines

    @property
    def has_anthropic_key(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_openrouter_key(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def has_any_key(self) -> bool:
        return self.has_anthropic_key or self.has_openai_key or self.has_openrouter_key

    @property
    def machine_id(self) -> str:
        """Global unique identifier for this machine instance."""
        return get_machine_id()

    @property
    def log_dir(self) -> Path:
        log_path = Path("logs")
        log_path.mkdir(exist_ok=True)
        return log_path

    def __repr__(self) -> str:
        """Override repr to never leak API keys."""
        return (
            f"Settings(host={self.host!r}, port={self.port}, "
            f"model={self.default_model!r}, engines={self.enabled_engines!r}, "
            f"policy={self.policy_mode.value!r}, "
            f"has_anthropic_key={self.has_anthropic_key}, "
            f"has_openai_key={self.has_openai_key})"
        )


# Singleton settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Force reload settings from .env (e.g. after key rotation)."""
    global _settings
    _settings = Settings()
    return _settings


def get_machine_id() -> str:
    """Load or generate a unique machine ID."""
    id_file = Path("clawbridge.id")
    if id_file.exists():
        return id_file.read_text().strip()
    mid = str(uuid.uuid4())
    id_file.write_text(mid)
    return mid
