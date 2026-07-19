"""SQLite initialization, migrations, and session construction."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.ensure_directories()
        self._run_migrations(settings.database_path)
        self.engine = self._create_engine(settings.database_path)
        self.session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, autoflush=False
        )

    @staticmethod
    def _run_migrations(path: Path) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            applied = {
                row[0] for row in connection.execute("SELECT version FROM schema_migrations")
            }
            migration_root = resources.files("linguaspindle.migrations")
            for item in sorted(migration_root.iterdir(), key=lambda candidate: candidate.name):
                if not item.name.endswith(".sql"):
                    continue
                version_text, _, name = item.name.partition("_")
                version = int(version_text)
                if version in applied:
                    continue
                connection.executescript(item.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) "
                    "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                    (version, name),
                )
                connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _create_engine(path: Path) -> Engine:
        engine = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 5},
        )

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection: sqlite3.Connection, _record: object) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        return engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def check(self) -> None:
        with self.session() as session:
            session.execute(__import__("sqlalchemy").text("SELECT 1"))

    def close(self) -> None:
        self.engine.dispose()
