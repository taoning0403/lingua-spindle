from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import subprocess
import sys
import threading
import zipfile
from importlib import resources
from pathlib import Path

import pytest

from linguaspindle.adapters.base import (
    AdapterHealth,
    AdapterManifest,
    AdapterRegistry,
    MangaAdapterResult,
)
from linguaspindle.config import Settings
from linguaspindle.database import Database
from linguaspindle.orchestration.engine import JobRunner
from linguaspindle.providers.base import ProviderRegistry, TranslationRequest, TranslationResult
from linguaspindle.runtime import LocalRuntime


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


def _create_v020_runtime_data(data_dir: Path) -> dict[str, object]:
    repository = Path(__file__).resolve().parents[2]
    wheel = (
        repository
        / "acceptance"
        / "v0.2.0"
        / "artifacts"
        / "wheel"
        / "linguaspindle-0.2.0-py3-none-any.whl"
    )
    script = r"""
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from linguaspindle import __version__
from linguaspindle.adapters.base import (
    Adapter,
    AdapterHealth,
    AdapterManifest,
    AdapterRegistry,
    MangaAdapterResult,
)
from linguaspindle.application import ApplicationService
from linguaspindle.config import Settings
from linguaspindle.errors import ErrorCode, LinguaError
from linguaspindle.orchestration.engine import JobRunner


class LegacyPartialMangaAdapter(Adapter):
    manifest = AdapterManifest(
        id="legacy-partial-manga",
        display_name="v0.2 partial manga Adapter",
        adapter_version="0.2-test",
        upstream_version="test",
        invocation_type="test_double",
        capabilities=("manga_full_pipeline",),
        input_formats=("png",),
        output_formats=("png",),
        languages=("*",),
        requires_gpu=False,
        supports_cancel=False,
        supports_progress=False,
        health_check="built-in test",
        configuration_help="test only",
        upstream_url="",
        upstream_license="Apache-2.0",
        modified=False,
    )

    def __init__(self):
        self.calls = 0

    def health(self):
        return AdapterHealth(True, "ready")

    def translate_image(self, *, image, filename, source_language, target_language):
        self.calls += 1
        if self.calls == 2:
            raise LinguaError(
                ErrorCode.EXTERNAL_COMMAND,
                "Synthetic legacy page failure",
                retryable=True,
            )
        return MangaAdapterResult(
            image=image,
            media_type="image/png",
            raw_metadata={"filename": filename, "target_language": target_language},
        )

data_dir = Path(sys.argv[2])
service = ApplicationService(Settings(data_dir=data_dir))
try:
    novel = service.create_project(
        name="v0.2 novel",
        kind="novel",
        source_language="en",
        target_language="fr",
        source_name="legacy.txt",
        source_bytes=b"First legacy paragraph.\n\nSecond legacy paragraph.\n",
        media_type="text/plain",
    )
    novel_job = service.create_job(project_id=novel["id"], provider_id="mock")
    JobRunner(service).run_once()

    partial_novel = service.create_project(
        name="v0.2 partial novel",
        kind="novel",
        source_language="en",
        target_language="fr",
        source_name="legacy-partial.txt",
        source_bytes=(
            b"Legacy translation stays.\n\n"
            b"Legacy [[MOCK_FAIL]] translation recovers.\n"
        ),
        media_type="text/plain",
    )
    partial_novel_job = service.create_job(
        project_id=partial_novel["id"], provider_id="mock"
    )
    JobRunner(service).run_once()

    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
        "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
    )
    comic = io.BytesIO()
    with zipfile.ZipFile(comic, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pages/1.png", png)
        archive.writestr("pages/2.png", png)
    manga = service.create_project(
        name="v0.2 manga",
        kind="manga",
        source_language="ja",
        target_language="en",
        source_name="legacy.cbz",
        source_bytes=comic.getvalue(),
        media_type="application/vnd.comicbook+zip",
    )
    manga_job = service.create_job(project_id=manga["id"], adapter_id="mock-manga")
    JobRunner(service).run_once()

    service.adapters = AdapterRegistry([LegacyPartialMangaAdapter()])
    partial_manga = service.create_project(
        name="v0.2 partial manga",
        kind="manga",
        source_language="ja",
        target_language="en",
        source_name="legacy-partial.cbz",
        source_bytes=comic.getvalue(),
        media_type="application/vnd.comicbook+zip",
    )
    partial_manga_job = service.create_job(
        project_id=partial_manga["id"], adapter_id="legacy-partial-manga"
    )
    JobRunner(service).run_once()

    projects = {
        "novel": novel["id"],
        "manga": manga["id"],
        "partial_novel": partial_novel["id"],
        "partial_manga": partial_manga["id"],
    }
    jobs = {
        "novel": novel_job["id"],
        "manga": manga_job["id"],
        "partial_novel": partial_novel_job["id"],
        "partial_manga": partial_manga_job["id"],
    }
    artifacts = []
    for project_id in projects.values():
        for artifact in service.list_artifacts(project_id=project_id):
            public, payload = service.read_artifact(artifact["id"])
            artifacts.append(
                {
                    "id": public["id"],
                    "project_id": public["project_id"],
                    "kind": public["kind"],
                    "size": len(payload),
                    "checksum": hashlib.sha256(payload).hexdigest(),
                }
            )
    summary = {
        "version": __version__,
        "projects": projects,
        "jobs": jobs,
        "artifacts": artifacts,
        "novel_segments": service.list_segments(novel["id"], job_id=novel_job["id"]),
        "partial_novel_segments": service.list_segments(
            partial_novel["id"], job_id=partial_novel_job["id"]
        ),
        "partial_job_statuses": {
            "novel": service.get_job(partial_novel_job["id"])["status"],
            "manga": service.get_job(partial_manga_job["id"])["status"],
        },
    }
finally:
    service.close()
print(json.dumps(summary))
"""
    completed = subprocess.run(  # noqa: S603 - fixed interpreter, tracked Wheel, test-owned paths
        [sys.executable, "-I", "-c", script, str(wheel), str(data_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class _RecoveryProvider:
    id = "mock"
    display_name = "v0.3 migration recovery Provider"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def configured(self) -> bool:
        return True

    def public_status(self) -> dict[str, object]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "configured": True,
            "model": "migration-recovery-v1",
        }

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls.append(request.text)
        recovered = request.text.replace("[[MOCK_FAIL]]", "").replace("  ", " ").strip()
        return TranslationResult(
            text=f"[recovered] {recovered}",
            model="migration-recovery-v1",
        )


_RECOVERY_MANGA_MANIFEST = AdapterManifest(
    id="legacy-partial-manga",
    display_name="v0.3 migration recovery manga Adapter",
    adapter_version="0.3-test",
    upstream_version="test",
    invocation_type="test_double",
    capabilities=("manga_full_pipeline",),
    input_formats=("png",),
    output_formats=("png",),
    languages=("*",),
    requires_gpu=False,
    supports_cancel=False,
    supports_progress=False,
    health_check="built-in test",
    configuration_help="test only",
    upstream_url="",
    upstream_license="Apache-2.0",
    modified=False,
)


class _RecoveryMangaAdapter:
    manifest = _RECOVERY_MANGA_MANIFEST

    def __init__(self) -> None:
        self.calls: list[str] = []

    def health(self) -> AdapterHealth:
        return AdapterHealth(True, "ready")

    def translate_image(
        self,
        *,
        image: bytes,
        filename: str,
        source_language: str,
        target_language: str,
    ) -> MangaAdapterResult:
        self.calls.append(filename)
        return MangaAdapterResult(
            image=image,
            media_type="image/png",
            raw_metadata={
                "filename": filename,
                "source_language": source_language,
                "target_language": target_language,
            },
        )


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

    assert versions == [1, 2, 3]
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
    assert segment["segment_key"] is None
    assert "ix_segments_project_input_hash" in indexes
    assert "ix_segments_job_document" in indexes
    assert "ix_segments_job_segment_key" in indexes


def test_v020_wheel_novel_and_manga_data_upgrade_without_loss(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "v020-data")
    before = _create_v020_runtime_data(settings.data_dir)
    assert before["version"] == "0.2.0"
    with sqlite3.connect(settings.database_path) as connection:
        assert [row[0] for row in connection.execute("SELECT version FROM schema_migrations")] == [
            1,
            2,
        ]

    thread_ids = {thread.ident for thread in threading.enumerate()}
    runtime = LocalRuntime(settings)
    assert {thread.ident for thread in threading.enumerate()} == thread_ids
    try:
        projects = before["projects"]
        jobs = before["jobs"]
        assert isinstance(projects, dict) and isinstance(jobs, dict)
        novel_id = str(projects["novel"])
        manga_id = str(projects["manga"])
        assert runtime.get_project(novel_id)["kind"] == "novel"
        assert runtime.get_project(manga_id)["kind"] == "manga"
        assert runtime.get_job(str(jobs["novel"]))["status"] == "succeeded"
        assert runtime.get_job(str(jobs["manga"]))["status"] == "succeeded"

        artifacts = before["artifacts"]
        assert isinstance(artifacts, list)
        manga_kinds: set[str] = set()
        for expected in artifacts:
            assert isinstance(expected, dict)
            artifact, payload = runtime.read_artifact(str(expected["id"]))
            assert artifact["project_id"] == expected["project_id"]
            assert artifact["kind"] == expected["kind"]
            assert len(payload) == expected["size"]
            assert hashlib.sha256(payload).hexdigest() == expected["checksum"]
            if artifact["project_id"] == manga_id:
                manga_kinds.add(str(artifact["kind"]))
        assert {
            "source_original",
            "manga_manifest",
            "manga_page_source",
            "manga_page_translated",
            "adapter_raw_output",
            "manga_export_cbz",
        } <= manga_kinds

        expected_segments = before["novel_segments"]
        current_segments = runtime.list_segments(novel_id, job_id=str(jobs["novel"]))
        assert isinstance(expected_segments, list)
        assert [segment["source_text"] for segment in current_segments] == [
            segment["source_text"] for segment in expected_segments
        ]
        assert [segment["translated_text"] for segment in current_segments] == [
            segment["translated_text"] for segment in expected_segments
        ]
        assert all(segment["segment_id"] for segment in current_segments)
    finally:
        runtime.close()

    with sqlite3.connect(settings.database_path) as connection:
        assert [row[0] for row in connection.execute("SELECT version FROM schema_migrations")] == [
            1,
            2,
            3,
        ]


def test_v020_partial_jobs_reprepare_immutable_sources_and_retry_to_completion(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "v020-partial-data")
    before = _create_v020_runtime_data(settings.data_dir)
    assert before["version"] == "0.2.0"
    assert before["partial_job_statuses"] == {
        "novel": "partially_succeeded",
        "manga": "partially_succeeded",
    }

    projects = before["projects"]
    jobs = before["jobs"]
    assert isinstance(projects, dict) and isinstance(jobs, dict)
    novel_id = str(projects["partial_novel"])
    novel_job_id = str(jobs["partial_novel"])
    manga_id = str(projects["partial_manga"])
    manga_job_id = str(jobs["partial_manga"])

    runtime = LocalRuntime(settings)
    provider = _RecoveryProvider()
    adapter = _RecoveryMangaAdapter()
    runtime.providers = ProviderRegistry([provider])
    runtime.adapters = AdapterRegistry([adapter])
    try:
        novel_artifacts_before = runtime.list_artifacts(project_id=novel_id)
        novel_source = next(
            artifact for artifact in novel_artifacts_before if artifact["kind"] == "source_original"
        )
        _, novel_source_payload = runtime.read_artifact(str(novel_source["id"]))
        novel_source_checksum = hashlib.sha256(novel_source_payload).hexdigest()

        legacy_segments = runtime.list_segments(novel_id, job_id=novel_job_id)
        assert [segment["status"] for segment in legacy_segments] == [
            "succeeded",
            "failed",
        ]
        assert legacy_segments[0]["translated_text"] == "[fr] Legacy translation stays."
        assert legacy_segments[1]["translated_text"] is None
        legacy_segment_ids = {str(segment["segment_id"]) for segment in legacy_segments}

        scheduled_novel = runtime.retry_job(novel_job_id)
        assert scheduled_novel["status"] == "queued"
        assert {step["status"] for step in scheduled_novel["steps"]} == {"pending"}
        assert JobRunner(runtime).run_once() is True

        completed_novel = runtime.get_job(novel_job_id)
        assert completed_novel["status"] == "succeeded"
        assert completed_novel["error"] is None
        novel_attempts = {step["key"]: step["attempt_count"] for step in completed_novel["steps"]}
        assert novel_attempts["detect_encoding"] == 2
        assert novel_attempts["extract_text"] == 2
        assert novel_attempts["segment_text"] == 2

        recovered_segments = runtime.list_segments(novel_id, job_id=novel_job_id)
        assert [segment["status"] for segment in recovered_segments] == [
            "succeeded",
            "succeeded",
        ]
        assert {str(segment["segment_id"]) for segment in recovered_segments}.isdisjoint(
            legacy_segment_ids
        )
        assert recovered_segments[0]["translated_text"] == "[fr] Legacy translation stays."
        assert recovered_segments[1]["translated_text"] == (
            "[recovered] Legacy translation recovers."
        )
        assert provider.calls == ["Legacy [[MOCK_FAIL]] translation recovers."]

        novel_artifacts_after = runtime.list_artifacts(project_id=novel_id)
        source_artifacts_after = [
            artifact for artifact in novel_artifacts_after if artifact["kind"] == "source_original"
        ]
        assert [artifact["id"] for artifact in source_artifacts_after] == [novel_source["id"]]
        _, novel_source_payload_after = runtime.read_artifact(str(novel_source["id"]))
        assert novel_source_payload_after == novel_source_payload
        assert hashlib.sha256(novel_source_payload_after).hexdigest() == novel_source_checksum

        novel_exports = [
            artifact for artifact in novel_artifacts_after if artifact["kind"] == "novel_export_txt"
        ]
        assert len(novel_exports) == 2
        _, novel_output = runtime.read_artifact(str(novel_exports[-1]["id"]))
        assert novel_output.decode() == (
            "[fr] Legacy translation stays.\n\n[recovered] Legacy translation recovers.\n"
        )

        manga_artifacts_before = runtime.list_artifacts(project_id=manga_id)
        manga_source = next(
            artifact for artifact in manga_artifacts_before if artifact["kind"] == "source_original"
        )
        _, manga_source_payload = runtime.read_artifact(str(manga_source["id"]))
        manga_source_checksum = hashlib.sha256(manga_source_payload).hexdigest()
        legacy_manifest_artifact = next(
            artifact for artifact in manga_artifacts_before if artifact["kind"] == "manga_manifest"
        )
        _, legacy_manifest_payload = runtime.read_artifact(str(legacy_manifest_artifact["id"]))
        legacy_manifest = json.loads(legacy_manifest_payload)
        assert legacy_manifest["version"] == 1
        assert "manifest" not in legacy_manifest
        assert len(legacy_manifest["pages"]) == 2
        legacy_page_artifact_ids = {str(page["artifact_id"]) for page in legacy_manifest["pages"]}

        scheduled_manga = runtime.retry_job(manga_job_id)
        assert scheduled_manga["status"] == "queued"
        assert {step["status"] for step in scheduled_manga["steps"]} == {"pending"}
        assert JobRunner(runtime).run_once() is True

        completed_manga = runtime.get_job(manga_job_id)
        assert completed_manga["status"] == "succeeded"
        assert completed_manga["error"] is None
        manga_attempts = {step["key"]: step["attempt_count"] for step in completed_manga["steps"]}
        assert manga_attempts["prepare_manga"] == 2
        assert manga_attempts["translate_manga"] == 2
        assert manga_attempts["export_manga"] == 2
        assert adapter.calls == ["1.png", "2.png"]

        manga_artifacts_after = runtime.list_artifacts(project_id=manga_id)
        manga_sources_after = [
            artifact for artifact in manga_artifacts_after if artifact["kind"] == "source_original"
        ]
        assert [artifact["id"] for artifact in manga_sources_after] == [manga_source["id"]]
        _, manga_source_payload_after = runtime.read_artifact(str(manga_source["id"]))
        assert manga_source_payload_after == manga_source_payload
        assert hashlib.sha256(manga_source_payload_after).hexdigest() == manga_source_checksum

        manifest_artifacts = [
            artifact for artifact in manga_artifacts_after if artifact["kind"] == "manga_manifest"
        ]
        assert len(manifest_artifacts) == 2
        _, canonical_manifest_payload = runtime.read_artifact(str(manifest_artifacts[-1]["id"]))
        canonical_manifest = json.loads(canonical_manifest_payload)
        assert canonical_manifest["schema_version"] == "runtime-manga-manifest.v1"
        assert canonical_manifest["source_artifact_id"] == manga_source["id"]
        assert canonical_manifest["manifest"]["source_sha256"] == manga_source_checksum
        assert len(canonical_manifest["manifest"]["pages"]) == 2
        canonical_page_artifact_ids = {
            str(page["artifact_id"]) for page in canonical_manifest["pages"]
        }
        assert len(canonical_page_artifact_ids) == 2
        assert canonical_page_artifact_ids.isdisjoint(legacy_page_artifact_ids)
        assert (
            len(
                [
                    artifact
                    for artifact in manga_artifacts_after
                    if artifact["kind"] == "manga_page_source"
                ]
            )
            == 4
        )

        translated_pages = [
            artifact
            for artifact in manga_artifacts_after
            if artifact["kind"] == "manga_page_translated"
        ]
        assert len(translated_pages) == 3
        manga_exports = [
            artifact for artifact in manga_artifacts_after if artifact["kind"] == "manga_export_cbz"
        ]
        assert len(manga_exports) == 2
        _, manga_output = runtime.read_artifact(str(manga_exports[-1]["id"]))
        with zipfile.ZipFile(io.BytesIO(manga_source_payload)) as source_archive:
            source_pages = [
                source_archive.read("pages/1.png"),
                source_archive.read("pages/2.png"),
            ]
        with zipfile.ZipFile(io.BytesIO(manga_output)) as archive:
            assert archive.namelist() == ["0001.png", "0002.png"]
            assert [archive.read(name) for name in archive.namelist()] == source_pages
    finally:
        runtime.close()


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
