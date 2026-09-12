"""Application configuration using Pydantic Settings."""

from pathlib import Path
from typing import Any

import structlog
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger()


class Settings(BaseSettings):
    """Trace runtime settings."""

    app_name: str = "Trace"
    version: str = "0.1.0"
    debug: bool = False

    # Primary database URL. Defaults to local PostgreSQL, can be overridden via TRACE_DATABASE_URL or .env
    # Example PostgreSQL: postgresql+psycopg://postgres:postgres@localhost:5432/trace
    # Example SQLite: sqlite:///trace.db
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/trace",
        alias="TRACE_DATABASE_URL",
    )

    # Optional secret encryption / auth key
    secret_key: SecretStr = Field(
        default=SecretStr("trace-local-dev-key-change-in-production"),
        alias="TRACE_SECRET_KEY",
    )

    # Base storage directory for cases & evidence
    storage_root: Path = Field(
        default_factory=lambda: Path.home() / ".trace" / "storage",
        alias="TRACE_STORAGE_ROOT",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def model_post_init(self, __context: Any) -> None:
        try:
            self.storage_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "Could not initialize storage directory",
                path=str(self.storage_root),
                error=str(exc),
            )


settings = Settings()
