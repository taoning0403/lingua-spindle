from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from linguaspindle.application import ApplicationService
from linguaspindle.config import Settings
from linguaspindle.epub import inspect_epub
from linguaspindle.errors import ErrorCode, LinguaError
from linguaspindle.interfaces.api import create_app
from linguaspindle.interfaces.cli import app as cli_app
from linguaspindle.models import Artifact, Project
from linguaspindle.orchestration.engine import JobRunner
from linguaspindle.providers.base import (
    ProviderRegistry,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)

_COVER_BYTES = b"\xff\xd8integration-cover\x00\xff\xd9"
_FONT_BYTES = b"wOF2-integration-font\x00\x01"
_CSS_BYTES = (
    b"@font-face{font-family:Fixture;src:url('../Fonts/fixture.woff2')}"
    b"body{background-image:url('../Images/cover.jpg')}"
)


def _write_epub(
    path: Path,
    *,
    version: str = "3.0",
    failing_segment: bool = False,
    protected: bool = False,
    unsafe_member: str | None = None,
    prose: str = "Hello from the first chapter.",
) -> bytes:
    container = b"""<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
    nav_properties = ' properties="nav"' if version == "3.0" else ""
    spine_toc = ' toc="ncx"' if version == "2.0" else ""
    package = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         unique-identifier="book-id" version="{version}">
  <metadata>
    <dc:identifier id="book-id">urn:uuid:integration-book</dc:identifier>
    <dc:title>Integration Book</dc:title>
    <dc:creator>Fixture Author</dc:creator>
    <dc:subject>Integration</dc:subject>
    <dc:description>A pipeline fixture.</dc:description>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter-1" href="Text/chapter-1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter-2" href="Text/chapter-2.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="Text/nav.xhtml" media-type="application/xhtml+xml"{nav_properties}/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="cover" href="Images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>
    <item id="css" href="Styles/book.css" media-type="text/css"/>
    <item id="font" href="Fonts/fixture.woff2" media-type="font/woff2"/>
  </manifest>
  <spine{spine_toc}>
    <itemref idref="chapter-1"/>
    <itemref idref="chapter-2"/>
  </spine>
</package>""".encode()
    marker = "[[MOCK_FAIL]] Keep this sentence." if failing_segment else "Translate this sentence."
    chapter_1 = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Structural title</title><link rel="stylesheet" href="../Styles/book.css"/></head>
  <body>
    <h1>Chapter One</h1>
    <p>{prose}</p>
    <p>{marker}</p>
    <p><a href="chapter-2.xhtml#footnote">Read the footnote</a></p>
    <img src="../Images/cover.jpg" alt="Cover illustration" title="Book cover"/>
  </body>
</html>""".encode()
    chapter_2 = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Second structural title</title>
    <link rel="stylesheet" href="../Styles/book.css"/></head>
  <body>
    <h1>Chapter Two</h1>
    <p id="footnote">A visible footnote.</p>
    <a href="chapter-1.xhtml">Return to chapter one</a>
  </body>
</html>"""
    nav = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title>Navigation</title></head>
  <body><nav epub:type="toc"><ol>
    <li><a href="chapter-1.xhtml">Chapter One</a></li>
    <li><a href="chapter-2.xhtml">Chapter Two</a></li>
  </ol></nav></body>
</html>"""
    ncx = b"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <docTitle><text>Integration Book</text></docTitle>
  <navMap>
    <navPoint id="one" playOrder="1"><navLabel><text>Chapter One</text></navLabel>
      <content src="Text/chapter-1.xhtml"/></navPoint>
    <navPoint id="two" playOrder="2"><navLabel><text>Chapter Two</text></navLabel>
      <content src="Text/chapter-2.xhtml#footnote"/></navPoint>
  </navMap>
</ncx>"""
    members = {
        "META-INF/container.xml": container,
        "OEBPS/content.opf": package,
        "OEBPS/Text/chapter-1.xhtml": chapter_1,
        "OEBPS/Text/chapter-2.xhtml": chapter_2,
        "OEBPS/Text/nav.xhtml": nav,
        "OEBPS/toc.ncx": ncx,
        "OEBPS/Images/cover.jpg": _COVER_BYTES,
        "OEBPS/Styles/book.css": _CSS_BYTES,
        "OEBPS/Fonts/fixture.woff2": _FONT_BYTES,
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, payload in members.items():
            archive.writestr(name, payload)
        if protected:
            archive.writestr("META-INF/encryption.xml", b"<encryption/>")
        if unsafe_member:
            archive.writestr(unsafe_member, b"must not escape")
    return path.read_bytes()


def _create_epub_project(
    service: ApplicationService,
    source_bytes: bytes,
    *,
    name: str = "EPUB integration",
    target_language: str = "zh-CN",
) -> dict:
    return service.create_project(
        name=name,
        kind="novel",
        source_language="en",
        target_language=target_language,
        source_name="fixture.epub",
        source_bytes=source_bytes,
        media_type="application/epub+zip",
    )


def test_epub_project_requires_a_bcp47_target_language(
    service: ApplicationService, tmp_path: Path
) -> None:
    source_path = tmp_path / "language-tag.epub"
    source_bytes = _write_epub(source_path)

    with pytest.raises(LinguaError) as caught:
        _create_epub_project(service, source_bytes, target_language="English")

    assert caught.value.code == ErrorCode.CONFIGURATION
    assert "BCP 47" in caught.value.message
    assert service.list_projects() == []


@pytest.mark.parametrize("version", ["2.0", "3.0"])
def test_epub_pipeline_roundtrip_preserves_source_and_binary_resources(
    service: ApplicationService,
    tmp_path: Path,
    version: str,
) -> None:
    fixture_path = tmp_path / f"source-{version}.epub"
    source_bytes = _write_epub(fixture_path, version=version)
    project = _create_epub_project(service, source_bytes, name=f"EPUB {version}")

    assert project["sources"][0]["kind"] == "epub"
    assert project["sources"][0]["metadata"]["epub_version"] == version
    source_artifact_id = project["sources"][0]["artifact_id"]
    job = service.create_job(project_id=project["id"], provider_id="mock")
    assert job["pipeline_key"] == "novel_epub_v1"

    assert JobRunner(service).run_once() is True

    completed = service.get_job(job["id"])
    assert completed["status"] == "succeeded"
    assert completed["progress"] == 1.0
    assert all(step["status"] == "succeeded" for step in completed["steps"])
    segments = service.list_segments(project["id"], job_id=job["id"])
    assert segments
    assert all(segment["status"] == "succeeded" for segment in segments)
    assert all(segment["translated_text"].startswith("[zh-CN]") for segment in segments)
    assert all(segment["source_artifact_id"] == source_artifact_id for segment in segments)
    assert all(segment["source_document"] for segment in segments)
    assert all(segment["locator"] for segment in segments)

    artifacts = service.list_artifacts(project_id=project["id"], job_id=job["id"])
    assert {
        "epub_package_manifest",
        "epub_segments",
        "epub_translations",
        "qa_report",
        "novel_export_epub",
        "epub_validation_report",
    } <= {artifact["kind"] for artifact in artifacts}
    validation_artifact = next(
        artifact for artifact in artifacts if artifact["kind"] == "epub_validation_report"
    )
    _, validation_payload = service.read_artifact(validation_artifact["id"])
    assert json.loads(validation_payload)["valid"] is True

    export_artifact = next(
        artifact for artifact in artifacts if artifact["kind"] == "novel_export_epub"
    )
    output_path = tmp_path / f"translated-{version}.epub"
    service.copy_artifact(export_artifact["id"], output_path)
    reimported = inspect_epub(output_path, service.settings)

    assert reimported["epub_version"] == version
    assert reimported["metadata"]["languages"] == ["zh-CN"]
    assert reimported["metadata"]["creators"] == ["Fixture Author"]
    translated_text = [unit["source_text"] for unit in reimported["text_units"]]
    assert "[zh-CN] Integration Book" in translated_text
    assert "[zh-CN] Hello from the first chapter." in translated_text
    assert "[zh-CN] A visible footnote." in translated_text

    _, persisted_source = service.read_artifact(source_artifact_id)
    assert persisted_source == source_bytes
    assert fixture_path.read_bytes() == source_bytes
    with zipfile.ZipFile(output_path) as archive:
        assert archive.infolist()[0].filename == "mimetype"
        assert archive.infolist()[0].compress_type == zipfile.ZIP_STORED
        assert archive.read("OEBPS/Images/cover.jpg") == _COVER_BYTES
        assert archive.read("OEBPS/Styles/book.css") == _CSS_BYTES
        assert archive.read("OEBPS/Fonts/fixture.woff2") == _FONT_BYTES


def test_second_identical_epub_job_reuses_every_translation_without_provider_calls(
    service: ApplicationService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_bytes = _write_epub(tmp_path / "reuse.epub")
    project = _create_epub_project(service, source_bytes, target_language="fr")
    provider = service.providers.get("mock")
    original_translate = provider.translate
    calls: list[str] = []

    def counting_translate(request: TranslationRequest) -> TranslationResult:
        calls.append(request.text)
        return original_translate(request)

    monkeypatch.setattr(provider, "translate", counting_translate)
    first_job = service.create_job(project_id=project["id"], provider_id="mock")
    assert JobRunner(service).run_once() is True
    first_segments = service.list_segments(project["id"], job_id=first_job["id"])
    assert calls
    assert all(segment["reused_from_segment_id"] is None for segment in first_segments)

    calls.clear()
    second_job = service.create_job(project_id=project["id"], provider_id="mock")
    assert JobRunner(service).run_once() is True
    second_segments = service.list_segments(project["id"], job_id=second_job["id"])

    assert service.get_job(second_job["id"])["status"] == "succeeded"
    assert calls == []
    assert len(second_segments) == len(first_segments)
    assert {segment["reused_from_segment_id"] for segment in second_segments} == {
        segment["id"] for segment in first_segments
    }
    assert [segment["translated_text"] for segment in second_segments] == [
        segment["translated_text"] for segment in first_segments
    ]
    segment_artifact = next(
        artifact
        for artifact in service.list_artifacts(project_id=project["id"], job_id=second_job["id"])
        if artifact["kind"] == "epub_segments"
    )
    _, segment_payload = service.read_artifact(segment_artifact["id"])
    assert json.loads(segment_payload)["reused_segment_count"] == len(second_segments)


def test_failed_epub_segment_falls_back_to_source_and_job_is_partial(
    service: ApplicationService,
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "partial.epub"
    source_bytes = _write_epub(fixture_path, failing_segment=True)
    project = _create_epub_project(service, source_bytes, target_language="de")
    job = service.create_job(project_id=project["id"], provider_id="mock")

    assert JobRunner(service).run_once() is True

    completed = service.get_job(job["id"])
    assert completed["status"] == "partially_succeeded"
    assert completed["error"]["code"] == ErrorCode.MODEL_API
    assert (
        next(step for step in completed["steps"] if step["key"] == "translate_text")["status"]
        == "partially_succeeded"
    )
    assert (
        next(step for step in completed["steps"] if step["key"] == "quality_check")["status"]
        == "succeeded"
    )
    assert (
        next(step for step in completed["steps"] if step["key"] == "export_epub")["status"]
        == "succeeded"
    )

    segments = service.list_segments(project["id"], job_id=job["id"])
    failed = [segment for segment in segments if segment["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["translated_text"] is None
    assert "[[MOCK_FAIL]]" in failed[0]["source_text"]
    assert any(finding["category"] == "missing_translation" for finding in failed[0]["qa_findings"])

    export_artifact = next(
        artifact
        for artifact in service.list_artifacts(project_id=project["id"], job_id=job["id"])
        if artifact["kind"] == "novel_export_epub"
    )
    output_path = tmp_path / "partial-translated.epub"
    service.copy_artifact(export_artifact["id"], output_path)
    translated_text = [
        unit["source_text"] for unit in inspect_epub(output_path, service.settings)["text_units"]
    ]
    assert "[[MOCK_FAIL]] Keep this sentence." in translated_text
    assert "[de] Hello from the first chapter." in translated_text
    _, persisted_source = service.read_artifact(project["sources"][0]["artifact_id"])
    assert persisted_source == source_bytes


@pytest.mark.parametrize(
    ("variation", "expected_code"),
    [
        ("damaged", ErrorCode.EPUB_INVALID),
        ("protected", ErrorCode.EPUB_PROTECTED),
        ("unsafe", ErrorCode.ARCHIVE_UNSAFE),
    ],
)
def test_invalid_epub_is_rejected_before_project_or_artifact_publication(
    service: ApplicationService,
    tmp_path: Path,
    variation: str,
    expected_code: ErrorCode,
) -> None:
    source_path = tmp_path / f"{variation}.epub"
    if variation == "damaged":
        source_bytes = b"this is not a ZIP archive"
    elif variation == "protected":
        source_bytes = _write_epub(source_path, protected=True)
    else:
        source_bytes = _write_epub(source_path, unsafe_member="../escaped.txt")

    with pytest.raises(LinguaError) as caught:
        _create_epub_project(service, source_bytes)

    assert caught.value.code == expected_code
    assert service.list_projects() == []
    with service.database.session() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(Artifact)) == 0
    assert [path for path in service.settings.artifacts_dir.rglob("*") if path.is_file()] == []


async def _assert_api_reads_cli_epub_state(data_dir: Path, project_id: str) -> None:
    application = create_app(Settings.from_env(data_dir), start_worker=False)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            project_response = await client.get(f"/api/projects/{project_id}")
            assert project_response.status_code == 200
            project = project_response.json()
            assert project["sources"][0]["kind"] == "epub"
            assert project["latest_job"]["pipeline_key"] == "novel_epub_v1"
            assert project["latest_job"]["status"] == "succeeded"

            artifacts_response = await client.get(f"/api/projects/{project_id}/artifacts")
            assert artifacts_response.status_code == 200
            artifacts = artifacts_response.json()
            epub_export = next(
                artifact for artifact in artifacts if artifact["kind"] == "novel_export_epub"
            )
            download = await client.get(epub_export["download_url"])
            assert download.status_code == 200
            assert download.headers["content-type"] == "application/epub+zip"
            with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
                assert archive.read("mimetype") == b"application/epub+zip"
                assert archive.read("OEBPS/Images/cover.jpg") == _COVER_BYTES


def test_cli_epub_job_is_immediately_visible_through_api(tmp_path: Path) -> None:
    data_dir = tmp_path / "shared-epub-data"
    source_path = tmp_path / "shared.epub"
    _write_epub(source_path)
    runner = CliRunner()
    created = runner.invoke(
        cli_app,
        [
            "projects",
            "create",
            "--name",
            "Shared EPUB",
            "--kind",
            "novel",
            "--source-language",
            "en",
            "--target-language",
            "es",
            "--source",
            str(source_path),
            "--data-dir",
            str(data_dir),
        ],
    )
    assert created.exit_code == 0, created.output
    project_id = json.loads(created.output)["id"]

    completed = runner.invoke(
        cli_app,
        ["run", project_id, "--provider", "mock", "--data-dir", str(data_dir)],
    )
    assert completed.exit_code == 0, completed.output
    assert json.loads(completed.output)["status"] == "succeeded"

    asyncio.run(_assert_api_reads_cli_epub_state(data_dir, project_id))


def test_runtime_provider_key_is_redacted_before_epub_reconstruction(tmp_path: Path) -> None:
    runtime_key = "sk-epub-export-secret-4e5085"

    class SecretEchoProvider(TranslationProvider):
        id = "secret-echo"
        display_name = "Secret echo test Provider"

        def configured(self) -> bool:
            return True

        def public_status(self) -> dict:
            return {
                "id": self.id,
                "display_name": self.display_name,
                "configured": True,
                "model": runtime_key,
            }

        def translate(self, request: TranslationRequest) -> TranslationResult:
            return TranslationResult(f"translated {runtime_key} {request.text}", runtime_key)

    source_path = tmp_path / "secret-safe.epub"
    _write_epub(source_path)
    settings = Settings(data_dir=tmp_path / "secret-data", openai_api_key=runtime_key)
    service = ApplicationService(settings)
    try:
        service.providers = ProviderRegistry([SecretEchoProvider()])
        project = _create_epub_project(service, source_path.read_bytes())
        job = service.create_job(project_id=project["id"], provider_id="secret-echo")

        assert JobRunner(service).run_once() is True
        assert service.get_job(job["id"])["status"] == "succeeded"
        exported = next(
            artifact
            for artifact in service.list_artifacts(project_id=project["id"], job_id=job["id"])
            if artifact["kind"] == "novel_export_epub"
        )
        _, exported_payload = service.read_artifact(exported["id"])
        assert runtime_key.encode() not in exported_payload
        with zipfile.ZipFile(io.BytesIO(exported_payload)) as archive:
            expanded_payload = b"".join(
                archive.read(member) for member in archive.infolist() if not member.is_dir()
            )
        assert runtime_key.encode() not in expanded_payload
        assert b"[REDACTED]" in expanded_payload
    finally:
        service.close()

    contaminated: list[Path] = []
    for path in settings.data_dir.rglob("*"):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        if runtime_key.encode() in payload:
            contaminated.append(path)
            continue
        if path.suffix.lower() not in {".epub", ".zip", ".cbz"}:
            continue
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if any(runtime_key.encode() in archive.read(member) for member in archive.infolist()):
                contaminated.append(path)
    assert contaminated == []


def test_epub_user_prose_with_secret_shaped_words_round_trips_unchanged(
    service: ApplicationService, tmp_path: Path
) -> None:
    prose = "The password: castle is a clue; secret=plot is ordinary prose."
    source_path = tmp_path / "ordinary-prose.epub"
    source_bytes = _write_epub(source_path, prose=prose)
    project = _create_epub_project(service, source_bytes, name="Password: castle story")
    job = service.create_job(project_id=project["id"], provider_id="mock")

    assert JobRunner(service).run_once() is True
    assert service.get_job(job["id"])["status"] == "succeeded"
    segments = service.list_segments(project["id"], job_id=job["id"])
    prose_segment = next(segment for segment in segments if segment["source_text"] == prose)
    assert prose in prose_segment["translated_text"]

    artifacts = service.list_artifacts(project_id=project["id"], job_id=job["id"])
    manifest = next(item for item in artifacts if item["kind"] == "epub_package_manifest")
    _, manifest_payload = service.read_artifact(manifest["id"])
    assert prose.encode() in manifest_payload
    assert b"[REDACTED]" not in manifest_payload

    exported = next(item for item in artifacts if item["kind"] == "novel_export_epub")
    _, exported_payload = service.read_artifact(exported["id"])
    with zipfile.ZipFile(io.BytesIO(exported_payload)) as archive:
        expanded = b"".join(
            archive.read(member) for member in archive.infolist() if not member.is_dir()
        )
    assert prose.encode() in expanded
    assert b"[REDACTED]" not in expanded
