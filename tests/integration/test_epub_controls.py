from __future__ import annotations

import threading
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from linguaspindle.application import ApplicationService
from linguaspindle.config import Settings
from linguaspindle.errors import ErrorCode, LinguaError
from linguaspindle.orchestration.engine import JobRunner
from linguaspindle.providers.base import (
    ProviderRegistry,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)


def _write_control_epub(path: Path) -> bytes:
    container = b"""<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
    package = b"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         unique-identifier="book-id" version="3.0">
  <metadata>
    <dc:identifier id="book-id">urn:uuid:epub-control-fixture</dc:identifier>
    <dc:title>Control fixture title</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="Text/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine><itemref idref="chapter"/></spine>
</package>"""
    chapter = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Structural title</title></head>
  <body>
    <p>First durable segment.</p>
    <p>Deterministic failure segment.</p>
    <p>Last pending segment.</p>
  </body>
</html>"""
    navigation = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title>Navigation structure</title></head>
  <body><nav epub:type="toc"><ol>
    <li><a href="chapter.xhtml">Unique navigation label.</a></li>
  </ol></nav></body>
</html>"""

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("EPUB/package.opf", package)
        archive.writestr("EPUB/Text/chapter.xhtml", chapter)
        archive.writestr("EPUB/Text/nav.xhtml", navigation)
    return path.read_bytes()


def _create_epub_job(
    service: ApplicationService,
    source_bytes: bytes,
    provider: TranslationProvider,
) -> tuple[dict[str, Any], dict[str, Any]]:
    service.providers = ProviderRegistry([provider])
    project = service.create_project(
        name="EPUB controls",
        kind="novel",
        source_language="en",
        target_language="es",
        source_name="controls.epub",
        source_bytes=source_bytes,
        media_type="application/epub+zip",
    )
    job = service.create_job(project_id=project["id"], provider_id=provider.id)
    assert job["pipeline_key"] == "novel_epub_v1"
    return project, job


def _wait_for_status(
    service: ApplicationService,
    job_id: str,
    expected: set[str],
    timeout: float = 5.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    job: dict[str, Any] = {}
    while time.monotonic() < deadline:
        job = service.get_job(job_id)
        if job["status"] in expected:
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job did not reach one of {sorted(expected)}; last state: {job}")


def _step(job: dict[str, Any], key: str) -> dict[str, Any]:
    return next(step for step in job["steps"] if step["key"] == key)


class _RecordingProvider(TranslationProvider):
    id = "epub-control-provider"
    display_name = "EPUB control test Provider"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def configured(self) -> bool:
        return True

    def public_status(self) -> dict[str, Any]:
        return {"id": self.id, "display_name": self.display_name, "configured": True}

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls.append(request.text)
        return TranslationResult(f"[es] {request.text}", "epub-control-v1")


class _BoundaryProvider(_RecordingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.completed = threading.Event()

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls.append(request.text)
        if len(self.calls) == 1:
            self.entered.set()
            if not self.release.wait(5.0):
                raise LinguaError(ErrorCode.TIMEOUT, "Controlled Provider release timed out")
            self.completed.set()
        return TranslationResult(f"[es] {request.text}", "epub-control-v1")


class _FailOnceProvider(_RecordingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.call_counts: Counter[str] = Counter()

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls.append(request.text)
        self.call_counts[request.text] += 1
        if request.text == "Deterministic failure segment." and self.call_counts[request.text] == 1:
            raise LinguaError(
                ErrorCode.MODEL_API,
                "Deterministic EPUB segment failure",
                retryable=True,
            )
        return TranslationResult(f"[es] {request.text}", "epub-control-v1")


class _SimulatedProcessExit(BaseException):
    pass


class _CrashOnSecondSegmentProvider(_RecordingProvider):
    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls.append(request.text)
        if len(self.calls) == 2:
            raise _SimulatedProcessExit("simulated process exit")
        return TranslationResult(f"[es] {request.text}", "epub-control-v1")


def test_running_epub_pause_resume_preserves_completed_segments(
    service: ApplicationService,
    tmp_path: Path,
) -> None:
    provider = _BoundaryProvider()
    project, job = _create_epub_job(service, _write_control_epub(tmp_path / "pause.epub"), provider)
    runner = JobRunner(service)
    runner.start(recover=False)
    try:
        assert provider.entered.wait(5.0)
        pausing = service.pause_job(job["id"])
        assert pausing["status"] == "running"
        assert pausing["control_request"] == "pause"

        provider.release.set()
        paused = _wait_for_status(service, job["id"], {"paused"})
        translate = _step(paused, "translate_text")
        assert translate["status"] == "paused"
        assert translate["attempt_count"] == 1
        paused_segments = service.list_segments(project["id"], job_id=job["id"])
        completed = [segment for segment in paused_segments if segment["status"] == "succeeded"]
        assert len(completed) == 1
        assert all(
            segment["status"] == "pending"
            for segment in paused_segments
            if segment["id"] != completed[0]["id"]
        )
        completed_snapshot = {
            key: completed[0][key]
            for key in ("id", "source_text", "translated_text", "source_document", "locator")
        }

        assert service.resume_job(job["id"])["status"] == "queued"
        succeeded = _wait_for_status(service, job["id"], {"succeeded"})
        final_segments = service.list_segments(project["id"], job_id=job["id"])

        assert _step(succeeded, "translate_text")["attempt_count"] == 2
        assert all(segment["status"] == "succeeded" for segment in final_segments)
        assert len(provider.calls) == len(final_segments)
        assert Counter(provider.calls) == Counter(
            segment["source_text"] for segment in final_segments
        )
        preserved = next(
            segment for segment in final_segments if segment["id"] == completed_snapshot["id"]
        )
        assert {
            key: preserved[key]
            for key in ("id", "source_text", "translated_text", "source_document", "locator")
        } == completed_snapshot
    finally:
        provider.release.set()
        runner.stop()


def test_running_epub_cancel_finishes_at_a_segment_boundary(
    service: ApplicationService,
    tmp_path: Path,
) -> None:
    provider = _BoundaryProvider()
    project, job = _create_epub_job(
        service,
        _write_control_epub(tmp_path / "cancel.epub"),
        provider,
    )
    runner = JobRunner(service)
    runner.start(recover=False)
    try:
        assert provider.entered.wait(5.0)
        cancelling = service.cancel_job(job["id"])
        assert cancelling["status"] == "cancelling"
        assert cancelling["control_request"] == "cancel"
        assert not provider.completed.is_set()

        provider.release.set()
        cancelled = _wait_for_status(service, job["id"], {"cancelled"})
        segments = service.list_segments(project["id"], job_id=job["id"])

        assert provider.completed.is_set()
        assert provider.calls == [segments[0]["source_text"]]
        assert segments[0]["status"] == "succeeded"
        assert all(segment["status"] == "pending" for segment in segments[1:])
        assert cancelled["error"]["code"] == ErrorCode.CANCELLED
        translate = _step(cancelled, "translate_text")
        assert translate["status"] == "cancelled"
        assert any(
            log["message"] == "Cancellation reached a safe boundary" for log in translate["logs"]
        )
        assert not {"pending", "running", "paused", "cancelling"} & {
            step["status"] for step in cancelled["steps"]
        }
    finally:
        provider.release.set()
        runner.stop()


def test_epub_segment_failure_retry_preserves_successes_and_attempt_logs(
    service: ApplicationService,
    tmp_path: Path,
) -> None:
    provider = _FailOnceProvider()
    project, job = _create_epub_job(service, _write_control_epub(tmp_path / "retry.epub"), provider)
    runner = JobRunner(service)

    assert runner.run_once() is True
    partial = service.get_job(job["id"])
    first_segments = service.list_segments(project["id"], job_id=job["id"])
    failed = [segment for segment in first_segments if segment["status"] == "failed"]
    succeeded = [segment for segment in first_segments if segment["status"] == "succeeded"]
    assert partial["status"] == "partially_succeeded"
    assert partial["error"]["code"] == ErrorCode.MODEL_API
    assert len(failed) == 1
    assert failed[0]["source_text"] == "Deterministic failure segment."
    assert succeeded
    succeeded_snapshots = {
        segment["id"]: (segment["translated_text"], segment["source_document"], segment["locator"])
        for segment in succeeded
    }

    retried = service.retry_job(job["id"])
    scheduled = _step(retried, "translate_text")
    retry_logs = [log for log in scheduled["logs"] if log["message"] == "Step scheduled for retry"]
    assert len(retry_logs) == 1
    assert retry_logs[0]["details"]["previous_status"] == "partially_succeeded"
    assert retry_logs[0]["details"]["previous_error"] == ErrorCode.MODEL_API

    assert runner.run_once() is True
    completed = service.get_job(job["id"])
    final_segments = service.list_segments(project["id"], job_id=job["id"])
    translate = _step(completed, "translate_text")

    assert completed["status"] == "succeeded"
    assert all(segment["status"] == "succeeded" for segment in final_segments)
    assert provider.call_counts[failed[0]["source_text"]] == 2
    assert all(provider.call_counts[segment["source_text"]] == 1 for segment in succeeded)
    assert {
        segment["id"]: (segment["translated_text"], segment["source_document"], segment["locator"])
        for segment in final_segments
        if segment["id"] in succeeded_snapshots
    } == succeeded_snapshots
    assert translate["attempt_count"] == 2
    assert [
        log["details"]["attempt"] for log in translate["logs"] if log["message"] == "Step started"
    ] == [1, 2]
    assert _step(completed, "inspect_epub")["attempt_count"] == 1
    assert _step(completed, "segment_epub")["attempt_count"] == 1
    assert _step(completed, "quality_check")["attempt_count"] == 2
    assert _step(completed, "export_epub")["attempt_count"] == 2


def test_epub_restart_recovery_preserves_lineage_and_reuses_completed_segments(
    tmp_path: Path,
) -> None:
    settings = Settings.from_env(tmp_path / "persistent-epub-data")
    crashed_provider = _CrashOnSecondSegmentProvider()
    first = ApplicationService(settings)
    project, job = _create_epub_job(
        first,
        _write_control_epub(tmp_path / "recovery.epub"),
        crashed_provider,
    )
    try:
        with pytest.raises(_SimulatedProcessExit, match="simulated process exit"):
            JobRunner(first).run_once()

        interrupted_job = first.get_job(job["id"])
        interrupted_segments = first.list_segments(project["id"], job_id=job["id"])
        assert interrupted_job["status"] == "running"
        assert _step(interrupted_job, "translate_text")["status"] == "running"
        assert [segment["status"] for segment in interrupted_segments[:2]] == [
            "succeeded",
            "running",
        ]
        lineage = {
            segment["id"]: (segment["source_document"], segment["locator"])
            for segment in interrupted_segments
        }
        assert all(document and locator for document, locator in lineage.values())
        preserved_success = interrupted_segments[0]
        interrupted_id = interrupted_segments[1]["id"]
    finally:
        first.close()

    second = ApplicationService(settings)
    retry_provider = _RecordingProvider()
    second.providers = ProviderRegistry([retry_provider])
    try:
        assert second.recover_interrupted_jobs() == 1
        recovered = second.get_job(job["id"])
        recovered_segments = second.list_segments(project["id"], job_id=job["id"])
        interrupted = next(
            segment for segment in recovered_segments if segment["id"] == interrupted_id
        )

        assert recovered["status"] == "failed"
        assert recovered["error"]["code"] == ErrorCode.PROCESS_INTERRUPTED
        translate = _step(recovered, "translate_text")
        assert translate["status"] == "failed"
        assert translate["error"]["code"] == ErrorCode.PROCESS_INTERRUPTED
        assert interrupted["status"] == "failed"
        assert interrupted["error"]["code"] == ErrorCode.PROCESS_INTERRUPTED
        assert {
            segment["id"]: (segment["source_document"], segment["locator"])
            for segment in recovered_segments
        } == lineage

        assert second.retry_job(job["id"])["status"] == "queued"
        assert JobRunner(second).run_once() is True
        completed = second.get_job(job["id"])
        final_segments = second.list_segments(project["id"], job_id=job["id"])

        assert completed["status"] == "succeeded"
        assert all(segment["status"] == "succeeded" for segment in final_segments)
        assert preserved_success["source_text"] not in retry_provider.calls
        preserved = next(
            segment for segment in final_segments if segment["id"] == preserved_success["id"]
        )
        assert preserved["translated_text"] == preserved_success["translated_text"]
        assert len(retry_provider.calls) == len(final_segments) - 1
        assert {
            segment["id"]: (segment["source_document"], segment["locator"])
            for segment in final_segments
        } == lineage
        translate = _step(completed, "translate_text")
        assert translate["attempt_count"] == 2
        assert [
            log["details"]["attempt"]
            for log in translate["logs"]
            if log["message"] == "Step started"
        ] == [1, 2]
        retry_log = next(
            log for log in translate["logs"] if log["message"] == "Step scheduled for retry"
        )
        assert retry_log["details"]["previous_error"] == ErrorCode.PROCESS_INTERRUPTED
    finally:
        second.close()
