"""Validated runtime configuration.

Secrets intentionally live only in this runtime object. They are never part of persisted models
or public serialization.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from platformdirs import user_data_path

from .limits import ArchiveLimits


class ConfigurationError(ValueError):
    """Raised when an environment setting is invalid."""


def _env_int(name: str, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{name} must be at most {maximum}")
    return value


def _env_float(
    name: str, default: float, minimum: float = 0.0, maximum: float | None = None
) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if not math.isfinite(value):
        raise ConfigurationError(f"{name} must be finite")
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{name} must be at most {maximum}")
    return value


def _base_url(name: str, value: str) -> str:
    candidate = value.strip().rstrip("/")
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError(f"{name} is not a valid URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigurationError(f"{name} must be an http or https URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigurationError(
            f"{name} cannot contain credentials, a query string, or a fragment"
        )
    if port is not None and not 1 <= port <= 65535:
        raise ConfigurationError(f"{name} contains an invalid port")
    return candidate


@dataclass(slots=True)
class Settings:
    """All process configuration, with secret fields excluded from representations."""

    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "INFO"
    worker_poll_seconds: float = 0.25
    max_upload_bytes: int = 100 * 1024 * 1024
    max_archive_files: int = 2_000
    max_archive_uncompressed_bytes: int = 1_000 * 1024 * 1024
    max_archive_member_bytes: int = 100 * 1024 * 1024
    max_archive_compression_ratio: float = 100.0
    max_archive_path_depth: int = 20
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = field(default=None, repr=False)
    openai_model: str = "gpt-4.1-mini"
    openai_timeout_seconds: float = 60.0
    openai_concurrency_limit: int = 2
    openai_max_retries: int = 3
    mit_base_url: str | None = None
    mit_timeout_seconds: float = 600.0
    mit_config_json: str = field(default="{}", repr=False)

    @classmethod
    def from_env(cls, data_dir: Path | str | None = None) -> Settings:
        configured_dir = data_dir or os.getenv("LINGUASPINDLE_DATA_DIR")
        root = (
            Path(configured_dir).expanduser()
            if configured_dir
            else Path(user_data_path("LinguaSpindle", appauthor=False))
        )
        host = os.getenv("LINGUASPINDLE_HOST", "127.0.0.1").strip()
        if not host:
            raise ConfigurationError("LINGUASPINDLE_HOST cannot be empty")
        log_level = os.getenv("LINGUASPINDLE_LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("LINGUASPINDLE_LOG_LEVEL is invalid")
        base_url = _base_url(
            "LINGUASPINDLE_OPENAI_BASE_URL",
            os.getenv("LINGUASPINDLE_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        mit_base_url_value = os.getenv("LINGUASPINDLE_MIT_BASE_URL") or None
        mit_base_url = (
            _base_url("LINGUASPINDLE_MIT_BASE_URL", mit_base_url_value)
            if mit_base_url_value
            else None
        )
        openai_model = os.getenv("LINGUASPINDLE_OPENAI_MODEL", "gpt-4.1-mini").strip()
        if not openai_model:
            raise ConfigurationError("LINGUASPINDLE_OPENAI_MODEL cannot be empty")
        mit_config_json = os.getenv("LINGUASPINDLE_MIT_CONFIG_JSON", "{}")
        try:
            mit_config = json.loads(mit_config_json)
        except json.JSONDecodeError as exc:
            raise ConfigurationError("LINGUASPINDLE_MIT_CONFIG_JSON must be valid JSON") from exc
        if not isinstance(mit_config, dict):
            raise ConfigurationError("LINGUASPINDLE_MIT_CONFIG_JSON must be a JSON object")
        return cls(
            data_dir=root.resolve(),
            host=host,
            port=_env_int("LINGUASPINDLE_PORT", 8765, 1, 65535),
            log_level=log_level,
            worker_poll_seconds=_env_float("LINGUASPINDLE_WORKER_POLL_SECONDS", 0.25, 0.05),
            max_upload_bytes=_env_int("LINGUASPINDLE_MAX_UPLOAD_BYTES", 100 * 1024 * 1024, 1),
            max_archive_files=_env_int("LINGUASPINDLE_MAX_ARCHIVE_FILES", 2_000, 1),
            max_archive_uncompressed_bytes=_env_int(
                "LINGUASPINDLE_MAX_ARCHIVE_BYTES", 1_000 * 1024 * 1024, 1
            ),
            max_archive_member_bytes=_env_int(
                "LINGUASPINDLE_MAX_ARCHIVE_MEMBER_BYTES",
                100 * 1024 * 1024,
                1,
                16 * 1024 * 1024 * 1024,
            ),
            max_archive_compression_ratio=_env_float(
                "LINGUASPINDLE_MAX_ARCHIVE_COMPRESSION_RATIO", 100.0, 1.0, 10_000.0
            ),
            max_archive_path_depth=_env_int("LINGUASPINDLE_MAX_ARCHIVE_PATH_DEPTH", 20, 1, 1_000),
            openai_base_url=base_url,
            openai_api_key=os.getenv("LINGUASPINDLE_OPENAI_API_KEY") or None,
            openai_model=openai_model,
            openai_timeout_seconds=_env_float("LINGUASPINDLE_OPENAI_TIMEOUT_SECONDS", 60.0, 0.1),
            openai_concurrency_limit=_env_int("LINGUASPINDLE_OPENAI_CONCURRENCY", 2, 1),
            openai_max_retries=_env_int("LINGUASPINDLE_OPENAI_MAX_RETRIES", 3, 0),
            mit_base_url=mit_base_url,
            mit_timeout_seconds=_env_float("LINGUASPINDLE_MIT_TIMEOUT_SECONDS", 600.0, 1.0),
            mit_config_json=mit_config_json,
        )

    @property
    def database_dir(self) -> Path:
        return self.data_dir / "database"

    @property
    def database_path(self) -> Path:
        return self.database_dir / "linguaspindle.sqlite3"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.database_dir,
            self.artifacts_dir,
            self.exports_dir,
            self.logs_dir,
            self.cache_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def archive_limits(self) -> ArchiveLimits:
        """Map process configuration to one explicit core operation contract."""

        return ArchiveLimits(
            max_files=self.max_archive_files,
            max_uncompressed_bytes=self.max_archive_uncompressed_bytes,
            max_member_bytes=self.max_archive_member_bytes,
            max_compression_ratio=self.max_archive_compression_ratio,
            max_path_depth=self.max_archive_path_depth,
        )
