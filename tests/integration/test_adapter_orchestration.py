from __future__ import annotations

import io
import threading
import time
import zipfile

from linguaspindle.adapters.base import (
    Adapter,
    AdapterHealth,
    AdapterManifest,
    AdapterRegistry,
    MangaAdapterResult,
)
from linguaspindle.application import ApplicationService
from linguaspindle.errors import ErrorCode, LinguaError
from linguaspindle.orchestration.engine import JobRunner

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
    "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
)

TEST_MANIFEST = AdapterManifest(
    id="controlled-manga",
    display_name="Controlled manga Adapter",
    adapter_version="1",
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


def _manga_job(service: ApplicationService, adapter: Adapter) -> tuple[dict, dict]:
    service.adapters = AdapterRegistry([adapter])
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("001.png", PNG_1X1)
        archive.writestr("002.png", PNG_1X1)
    project = service.create_project(
        name="Controlled manga",
        kind="manga",
        source_language="ja",
        target_language="en",
        source_name="controlled.cbz",
        source_bytes=source.getvalue(),
    )
    job = service.create_job(project_id=project["id"], adapter_id=adapter.manifest.id)
    return project, job


def _wait_for_status(service: ApplicationService, job_id: str, status: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.get_job(job_id)
        if job["status"] == status:
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job did not reach {status}")


class BlockingAdapter(Adapter):
    manifest = TEST_MANIFEST

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.completed = threading.Event()
        self.calls = 0

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
        self.calls += 1
        self.entered.set()
        if not self.release.wait(5):
            raise LinguaError(ErrorCode.TIMEOUT, "Test Adapter release timed out")
        self.completed.set()
        return MangaAdapterResult(
            image=image,
            media_type="image/png",
            raw_metadata={"filename": filename, "target": target_language},
        )


class PartialAdapter(Adapter):
    manifest = TEST_MANIFEST

    def __init__(self) -> None:
        self.calls = 0
        self.health_calls = 0

    def health(self) -> AdapterHealth:
        self.health_calls += 1
        return AdapterHealth(True, "ready")

    def translate_image(
        self,
        *,
        image: bytes,
        filename: str,
        source_language: str,
        target_language: str,
    ) -> MangaAdapterResult:
        self.calls += 1
        if self.calls == 1:
            raise LinguaError(
                ErrorCode.EXTERNAL_COMMAND,
                "Synthetic page failure",
                retryable=True,
            )
        return MangaAdapterResult(
            image=image,
            media_type="image/png",
            raw_metadata={"filename": filename, "source": source_language},
        )


def test_non_interruptible_adapter_remains_cancelling_until_page_boundary(
    service: ApplicationService,
) -> None:
    adapter = BlockingAdapter()
    project, job = _manga_job(service, adapter)
    runner = JobRunner(service)
    runner.start(recover=False)
    try:
        assert adapter.entered.wait(5)
        cancelling = service.cancel_job(job["id"])
        assert cancelling["status"] == "cancelling"
        assert adapter.calls == 1
        assert not adapter.completed.is_set()

        adapter.release.set()
        cancelled = _wait_for_status(service, job["id"], "cancelled")
        assert adapter.completed.is_set()
        assert adapter.calls == 1
        translated = service.list_artifacts(project_id=project["id"], job_id=job["id"])
        assert len([item for item in translated if item["kind"] == "manga_page_translated"]) == 1
        translate_step = next(
            step for step in cancelled["steps"] if step["key"] == "translate_manga"
        )
        assert translate_step["status"] == "cancelled"
        assert (
            next(step for step in cancelled["steps"] if step["key"] == "export_manga")["status"]
            == "cancelled"
        )
    finally:
        adapter.release.set()
        runner.stop()


def test_partial_adapter_run_keeps_raw_failures_and_exports_successful_pages(
    service: ApplicationService,
) -> None:
    adapter = PartialAdapter()
    project, job = _manga_job(service, adapter)
    assert JobRunner(service).run_once() is True

    completed = service.get_job(job["id"])
    assert completed["status"] == "partially_succeeded"
    translate_step = next(step for step in completed["steps"] if step["key"] == "translate_manga")
    assert translate_step["status"] == "partially_succeeded"
    assert translate_step["error"]["code"] == ErrorCode.EXTERNAL_COMMAND
    assert any("page Adapter invocation failed" in log["message"] for log in translate_step["logs"])

    artifacts = service.list_artifacts(project_id=project["id"], job_id=job["id"])
    assert len([item for item in artifacts if item["kind"] == "adapter_raw_output"]) == 2
    assert len([item for item in artifacts if item["kind"] == "manga_page_translated"]) == 1
    exported = next(item for item in artifacts if item["kind"] == "manga_export_cbz")
    _, payload = service.read_artifact(exported["id"])
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == ["0001.png"]

    scheduled = service.retry_job(job["id"])
    assert scheduled["status"] == "queued"
    assert (
        next(step for step in scheduled["steps"] if step["key"] == "prepare_manga")["status"]
        == "succeeded"
    )
    assert JobRunner(service).run_once() is True

    recovered = service.get_job(job["id"])
    assert recovered["status"] == "succeeded"
    attempts = {step["key"]: step["attempt_count"] for step in recovered["steps"]}
    assert attempts == {"prepare_manga": 1, "translate_manga": 2, "export_manga": 2}
    assert adapter.calls == 3
    assert adapter.health_calls == 2
    translate_logs = next(step for step in recovered["steps"] if step["key"] == "translate_manga")[
        "logs"
    ]
    assert any(log["details"].get("reused_pages") == 1 for log in translate_logs)


def test_unconfigured_real_adapter_fails_with_stable_diagnostic(
    service: ApplicationService,
) -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("001.png", PNG_1X1)
    project = service.create_project(
        name="Missing Adapter",
        kind="manga",
        source_language="ja",
        target_language="en",
        source_name="missing.cbz",
        source_bytes=source.getvalue(),
    )
    job = service.create_job(project_id=project["id"], adapter_id="manga-image-translator-http")
    assert JobRunner(service).run_once() is True
    failed = service.get_job(job["id"])
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == ErrorCode.ADAPTER_UNAVAILABLE
    assert "not configured" in failed["error"]["message"]
