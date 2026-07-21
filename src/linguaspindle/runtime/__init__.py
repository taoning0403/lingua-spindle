"""Optional local persistence runtime.

Install ``linguaspindle[runtime]`` before importing this package. Constructing
``LocalRuntime`` opens SQLite and the configured Artifact store, but never
starts a background worker; callers opt into ``JobRunner.start()`` explicitly.
"""

try:
    from ..application import ApplicationService
    from ..config import Settings
    from ..database import Database
    from ..orchestration.engine import JobRunner
    from ..storage import ArtifactStore
except ModuleNotFoundError as exc:  # pragma: no cover - exercised in isolated Wheel checks
    if exc.name not in {"platformdirs", "sqlalchemy"}:
        raise
    raise ModuleNotFoundError(
        "Local persistence is optional; install 'linguaspindle[runtime]'",
        name=exc.name,
    ) from exc


class LocalRuntime(ApplicationService):
    """Named v0.3 facade over the v0.2-compatible persistent implementation."""


__all__ = [
    "ArtifactStore",
    "Database",
    "JobRunner",
    "LocalRuntime",
    "Settings",
]
