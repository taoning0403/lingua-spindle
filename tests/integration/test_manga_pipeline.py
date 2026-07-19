from __future__ import annotations

import io
import zipfile

from linguaspindle.application import ApplicationService
from linguaspindle.orchestration.engine import JobRunner


def test_mock_manga_pipeline_preserves_pages_and_exports_cbz(
    service: ApplicationService,
) -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("001.png", b"not-a-real-png-but-contract-safe")
        archive.writestr("chapter/002.jpg", b"not-a-real-jpeg")
    project = service.create_project(
        name="Manga sample",
        kind="manga",
        source_language="ja",
        target_language="en",
        source_name="sample.cbz",
        source_bytes=source.getvalue(),
        media_type="application/vnd.comicbook+zip",
    )
    job = service.create_job(project_id=project["id"], adapter_id="mock-manga")

    JobRunner(service).run_once()

    completed = service.get_job(job["id"])
    assert completed["status"] == "succeeded"
    artifacts = service.list_artifacts(project_id=project["id"], job_id=job["id"])
    assert len([item for item in artifacts if item["kind"] == "manga_page_source"]) == 2
    assert len([item for item in artifacts if item["kind"] == "manga_page_translated"]) == 2
    exported = next(item for item in artifacts if item["kind"] == "manga_export_cbz")
    _, payload = service.read_artifact(exported["id"])
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == ["0001.png", "0002.jpg"]


def test_archive_traversal_is_rejected(service: ApplicationService) -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../escape.png", b"payload")
    project = service.create_project(
        name="Unsafe manga",
        kind="manga",
        source_language="ja",
        target_language="en",
        source_name="unsafe.cbz",
        source_bytes=source.getvalue(),
    )
    job = service.create_job(project_id=project["id"], adapter_id="mock-manga")
    JobRunner(service).run_once()
    failed = service.get_job(job["id"])
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "INVALID_FORMAT"


def test_nested_image_directory_is_normalized_to_a_cbz(
    service: ApplicationService, tmp_path
) -> None:
    source_dir = tmp_path / "pages"
    nested = source_dir / "chapter"
    nested.mkdir(parents=True)
    (source_dir / "001.png").write_bytes(b"first")
    (nested / "002.jpg").write_bytes(b"second")
    (nested / "ignored.txt").write_text("ignored", encoding="utf-8")

    project = service.create_project_from_path(
        name="Directory manga",
        kind="manga",
        source_language="ja",
        target_language="en",
        source_path=source_dir,
    )
    source = service.source_artifact(project["id"])
    _, payload = service.read_artifact(source.id)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == ["001.png", "chapter/002.jpg"]

    job = service.create_job(project_id=project["id"], adapter_id="mock-manga")
    assert JobRunner(service).run_once() is True
    assert service.get_job(job["id"])["status"] == "succeeded"
