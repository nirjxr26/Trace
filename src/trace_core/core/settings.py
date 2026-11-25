"""Application configuration using Pydantic Settings."""

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from trace_core.core.logging import get_logger

logger = get_logger()

DEV_SECRET_SENTINEL = "trace-local-dev-key-change-in-production"
# Shipped default database URL. Named once so the guard below cannot drift from the
# field default if either is rotated (was two reflective model_fields lookups).
DEV_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/trace"

_TRACE_HOME = Path.home() / ".trace"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILES = (str(_REPO_ROOT / ".env"), str(_TRACE_HOME / ".env"))


def _unknown_trace_settings(known: set[str]) -> set[str]:
    unknown = {name for name in os.environ if name.upper().startswith("TRACE_") and name.upper() not in known}
    for path in _ENV_FILES:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if "=" not in line:
                continue
            name = line.partition("=")[0].strip()
            if name.upper().startswith("TRACE_") and name.upper() not in known:
                unknown.add(name)
    return unknown


class Settings(BaseSettings):
    """Trace runtime settings."""

    version: str = "0.5.1"
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
        default=DEV_DATABASE_URL,
        alias="TRACE_DATABASE_URL",
    )

    # Optional secret encryption / auth key. Invariant: never rotate this while
    # HMAC-signed audit rows exist — old rows verify against the current value,
    # so rotation reads as ledger tampering. Rotate Ed25519 keys instead.
    secret_key: SecretStr = Field(
        default=SecretStr(DEV_SECRET_SENTINEL),
        alias="TRACE_SECRET_KEY",
    )

    # Base storage directory for cases & evidence
    storage_root: Path = Field(
        default_factory=lambda: _TRACE_HOME / "storage",
        alias="TRACE_STORAGE_ROOT",
    )

    # Deployment environment. Only development tolerates shipped defaults.
    env: str = Field(default="development", alias="TRACE_ENV")

    # Update channel + release manifest location (local path or https URL).
    # Defaults to the official Trace release manifest. Can be overridden via
    # TRACE_UPDATE_MANIFEST or .env, or disabled by setting TRACE_UPDATE_MANIFEST="".
    update_channel: Literal["stable", "beta"] = Field(default="stable", alias="TRACE_UPDATE_CHANNEL")
    update_manifest: str | None = Field(
        default="https://github.com/nirjxr26/Trace/releases/latest/download/stable.json",
        alias="TRACE_UPDATE_MANIFEST",
    )
    # Selects which device adapter is constructed. It does NOT bypass the
    # --allow-real-hardware opt-in [D27]: asking for `linux` still requires the
    # flag for any non-file target, so an env var can never silently authorise
    # real-device access.
    device_adapter: Literal["auto", "file", "linux", "win32"] = Field(default="auto", alias="TRACE_DEVICE_ADAPTER")

    # PostgreSQL pool. Defaults serve one workstation; multi-client deployments can
    # raise them without code changes. SQLite ignores all of these.
    db_pool_size: int = Field(default=5, ge=1, le=100, alias="TRACE_DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, ge=0, le=200, alias="TRACE_DB_MAX_OVERFLOW")
    db_pool_recycle: int = Field(default=1800, ge=0, le=86400, alias="TRACE_DB_POOL_RECYCLE")
    db_pool_timeout: int = Field(default=30, ge=1, le=300, alias="TRACE_DB_POOL_TIMEOUT")
    db_statement_timeout_ms: int = Field(default=300000, ge=1000, le=3600000, alias="TRACE_DB_STATEMENT_TIMEOUT_MS")

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def model_post_init(self, __context: Any) -> None:
        known = {str(field.alias).upper() for field in type(self).model_fields.values() if field.alias}
        for name in sorted(_unknown_trace_settings(known)):
            logger.warning("Unknown TRACE_ setting ignored", setting=name)
        if self.database_url == DEV_DATABASE_URL and self.debug:
            logger.warning(
                "Using shipped default database credentials; set TRACE_DATABASE_URL "
                "with a strong password before production use."
            )
        if self.env.strip().lower() == "production":
            if self.database_url == DEV_DATABASE_URL:
                raise ValueError("Refusing production startup on shipped default database credentials.")
            if self.secret_key.get_secret_value() == DEV_SECRET_SENTINEL:
                raise ValueError("Refusing production startup on shipped default secret key.")

    def ensure_storage(self) -> None:
        from trace_core.core.fs import ensure_dir

        try:
            ensure_dir(self.storage_root)
        except OSError as exc:
            logger.warning(
                "Could not initialize storage directory",
                path=str(self.storage_root),
                error=str(exc),
            )


settings = Settings()
