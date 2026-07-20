from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

import pytest

from linguaspindle.config import Settings
from linguaspindle.database import Database


def _create_v010_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "CREATE TABLE schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        migration = resources.files("linguaspindle.migrations").joinpath("0001_initial.sql")
        connection.executescript(migration.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO schema_migrations(version, name, applied_at) "
            "VALUES (1, 'initial.sql', '2026-07-19T00:00:00Z')"
        )
        connection.execute(
            "INSERT INTO projects VALUES "
            "('project', 'Existing novel', 'novel', 'en', 'fr', 'created', 'updated')"
        )
        connection.execute(
            "INSERT INTO artifacts VALUES ("
            "'artifact', 'project', NULL, NULL, 'source_original', 'novel.txt', "
            "'text/plain', 8, 'checksum', 'projects/project/artifact/novel.txt', '{}', 'created')"
        )
        connection.execute(
            "INSERT INTO sources ("
            "id, project_id, kind, original_name, media_type, size, checksum, artifact_id, "
            "created_at"
            ") VALUES ("
            "'source', 'project', 'txt', 'novel.txt', 'text/plain', 8, 'checksum', "
            "'artifact', 'created')"
        )
        connection.execute(
            "INSERT INTO jobs ("
            "id, project_id, translation_profile_id, pipeline_key, pipeline_version, provider_id, "
            "adapter_id, status, progress, control_request, profile_snapshot_json, requested_at, "
            "started_at, ended_at, updated_at, runner_token, error_code, error_message, "
            "error_details_json"
            ") VALUES ("
            "'job', 'project', NULL, 'novel_txt_v1', '1', 'mock', NULL, 'succeeded', 1.0, NULL, "
            "'{}', 'requested', 'started', 'ended', 'updated', NULL, NULL, NULL, NULL)"
        )
        connection.execute(
            "INSERT INTO translation_segments ("
            "id, project_id, job_id, sequence, source_text, translated_text, status, model, "
            "profile_snapshot_json, prompt_version, error_code, error_message, created_at, "
            "updated_at"
            ") VALUES ("
            "'segment', 'project', 'job', 0, 'Original', 'Traduit', 'succeeded', 'mock-v1', "
            "'{}', 'v1', NULL, NULL, 'created', 'updated')"
        )
        connection.commit()
    finally:
        connection.close()


def test_v010_database_is_upgraded_in_place_without_losing_data(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    _create_v010_database(settings.database_path)

    database = Database(settings)
    database.close()

    connection = sqlite3.connect(settings.database_path)
    connection.row_factory = sqlite3.Row
    try:
        versions = [
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        source = connection.execute("SELECT * FROM sources WHERE id = 'source'").fetchone()
        segment = connection.execute(
            "SELECT * FROM translation_segments WHERE id = 'segment'"
        ).fetchone()
        indexes = {
            row["name"] for row in connection.execute("PRAGMA index_list('translation_segments')")
        }
    finally:
        connection.close()

    assert versions == [1, 2]
    assert source is not None
    assert source["original_name"] == "novel.txt"
    assert source["metadata_json"] == "{}"
    assert segment is not None
    assert segment["source_text"] == "Original"
    assert segment["translated_text"] == "Traduit"
    assert segment["source_artifact_id"] is None
    assert segment["source_document"] is None
    assert segment["content_role"] is None
    assert segment["locator_json"] == "{}"
    assert segment["source_text_hash"] is None
    assert segment["translation_input_hash"] is None
    assert segment["reused_from_segment_id"] is None
    assert "ix_segments_project_input_hash" in indexes
    assert "ix_segments_job_document" in indexes


def test_failed_migration_rolls_back_schema_and_version_marker(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "atomic.sqlite3")
    try:
        connection.execute(
            "CREATE TABLE schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.execute("CREATE TABLE example (id INTEGER PRIMARY KEY)")
        connection.commit()

        with pytest.raises(sqlite3.OperationalError):
            Database._apply_migration(
                connection,
                version=99,
                name="broken.sql",
                sql=(
                    "ALTER TABLE example ADD COLUMN partial TEXT;\n"
                    "INSERT INTO table_that_does_not_exist VALUES (1);"
                ),
            )

        columns = {row[1] for row in connection.execute("PRAGMA table_info('example')").fetchall()}
        versions = connection.execute("SELECT version FROM schema_migrations").fetchall()
    finally:
        connection.close()

    assert columns == {"id"}
    assert versions == []
