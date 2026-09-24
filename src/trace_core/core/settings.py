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
    version: str = "0.2.3"
    # Alias-only binding: the documented TRACE_DEBUG name wins, and a stray
    # bare DEBUG in the environment can no longer crash startup with a bool error.
    debug: bool = Field(default=False, alias="TRACE_DEBUG")
    # SQL statement echo. Deliberately separate from debug: SQL logs carry case
    # content (titles, notes), so production keeps TRACE_SQL_ECHO=0.
    sql_echo: bool = Field(default=False, alias="TRACE_SQL_ECHO")

    # Primary database URL. Defaults to local PostgreSQL, can be overridden via TRACE_DATABASE_URL or .env
    # Example PostgreSQL: postgresql+psycopg://postgres:postgres@localhost:5432/trace
    # Example SQLite: sqlite:///trace.db
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/trace",
        alias="TRACE_DATABASE_URL",
    )

    # Optional secret encryption / auth key. Invariant: never rotate this while
    # HMAC-signed audit rows exist — old rows verify against the current value,
    # so rotation reads as ledger tampering. Rotate Ed25519 keys instead.
    secret_key: SecretStr = Field(
        default=SecretStr("trace-local-dev-key-change-in-production"),
        alias="TRACE_SECRET_KEY",
    )

    # Base storage directory for cases & evidence
    storage_root: Path = Field(
        default_factory=lambda: Path.home() / ".trace" / "storage",
        alias="TRACE_STORAGE_ROOT",
    )

    # Deployment environment. Only development tolerates shipped defaults.
    env: str = Field(default="development", alias="TRACE_ENV")

    # Update channel + release manifest location (local path or https URL).
    # Defaults to the official Trace release manifest. Can be overridden via
    # TRACE_UPDATE_MANIFEST or .env, or disabled by setting TRACE_UPDATE_MANIFEST="".
    update_channel: str = Field(default="stable", alias="TRACE_UPDATE_CHANNEL")
    update_manifest: str | None = Field(
        default="https://github.com/nirjxr26/Trace/releases/latest/download/stable.json",
        alias="TRACE_UPDATE_MANIFEST",
    )

    model_config = SettingsConfigDict(
        env_file=(".env", str(Path.home() / ".trace" / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def model_post_init(self, __context: Any) -> None:
        from trace_core.core.fs import ensure_dir

        try:
            ensure_dir(self.storage_root)
        except OSError as exc:
            logger.warning(
                "Could not initialize storage directory",
                path=str(self.storage_root),
                error=str(exc),
            )
        if self.database_url == Settings.model_fields["database_url"].default:
            logger.warning(
                "Using shipped default database credentials; set TRACE_DATABASE_URL "
                "with a strong password before production use."
            )
        if self.env.strip().lower() == "production":
            # Sentinel duplicated from signing.py by design: settings cannot import it (cycle).
            if self.database_url == Settings.model_fields["database_url"].default:
                raise ValueError("Refusing production startup on shipped default database credentials.")
            if self.secret_key.get_secret_value() == "trace-local-dev-key-change-in-production":
                raise ValueError("Refusing production startup on shipped default secret key.")


settings = Settings()
