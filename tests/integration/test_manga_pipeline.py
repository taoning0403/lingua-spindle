from __future__ import annotations

import io
import zipfile

import pytest

from linguaspindle.application import ApplicationService
from linguaspindle.errors import ErrorCode
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


@pytest.mark.parametrize(
    ("variation", "expected_code"),
    [
        ("member_size", ErrorCode.ARCHIVE_LIMIT_EXCEEDED),
        ("compression_ratio", ErrorCode.ARCHIVE_LIMIT_EXCEEDED),
        ("path_depth", ErrorCode.ARCHIVE_LIMIT_EXCEEDED),
        ("ambiguous_name", ErrorCode.ARCHIVE_UNSAFE),
        ("unicode_ambiguous_name", ErrorCode.ARCHIVE_UNSAFE),
        ("directory_members", ErrorCode.ARCHIVE_LIMIT_EXCEEDED),
    ],
)
def test_manga_archives_share_bounded_zip_security_rules(
    service: ApplicationService, variation: str, expected_code: ErrorCode
) -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if variation == "member_size":
            service.settings.max_archive_member_bytes = 16
            archive.writestr("page.png", b"x" * 32)
        elif variation == "compression_ratio":
            service.settings.max_archive_compression_ratio = 2
            archive.writestr("page.png", b"0" * 10_000)
        elif variation == "path_depth":
            service.settings.max_archive_path_depth = 3
            archive.writestr("a/b/c/page.png", b"image")
        elif variation == "ambiguous_name":
            archive.writestr("Page.PNG", b"one")
            archive.writestr("page.png", b"two")
        elif variation == "unicode_ambiguous_name":
            archive.writestr("caf\N{LATIN SMALL LETTER E WITH ACUTE}.png", b"one")
            archive.writestr("cafe\N{COMBINING ACUTE ACCENT}.png", b"two")
        else:
            service.settings.max_archive_files = 3
            archive.writestr("one/", b"")
            archive.writestr("two/", b"")
            archive.writestr("three/", b"")
            archive.writestr("page.png", b"image")
    project = service.create_project(
        name=f"Bounded manga {variation}",
        kind="manga",
        source_language="ja",
        target_language="en",
        source_name="bounded.cbz",
        source_bytes=source.getvalue(),
    )
    job = service.create_job(project_id=project["id"], adapter_id="mock-manga")

    JobRunner(service).run_once()

    failed = service.get_job(job["id"])
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == expected_code
