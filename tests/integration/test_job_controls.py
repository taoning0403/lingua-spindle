from __future__ import annotations

import threading
import time
from collections import Counter

from linguaspindle.application import ApplicationService
from linguaspindle.errors import ErrorCode, LinguaError
from linguaspindle.orchestration.engine import JobRunner
from linguaspindle.providers.base import (
    ProviderRegistry,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)


def _wait_for_status(
    service: ApplicationService, job_id: str, expected: set[str], timeout: float = 5.0
) -> dict:
    deadline = time.monotonic() + timeout
    job: dict = {}
    while time.monotonic() < deadline:
        job = service.get_job(job_id)
        if job["status"] in expected:
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job did not reach one of {sorted(expected)}; last state: {job}")


class ControlledProvider(TranslationProvider):
    id = "controlled"
    display_name = "Controlled test Provider"

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.completed = threading.Event()
        self.calls = 0

    def configured(self) -> bool:
        return True

    def public_status(self) -> dict:
        return {"id": self.id, "display_name": self.display_name, "configured": True}

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            if not self.release.wait(5):
                raise LinguaError(ErrorCode.TIMEOUT, "Test Provider release timed out")
            self.completed.set()
        return TranslationResult(f"[de] {request.text}", "controlled-v1")


class FlakyProvider(TranslationProvider):
    id = "flaky"
    display_name = "Flaky test Provider"

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()

    def configured(self) -> bool:
        return True

    def public_status(self) -> dict:
        return {"id": self.id, "display_name": self.display_name, "configured": True}

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls[request.text] += 1
        if "retry-me" in request.text and self.calls[request.text] == 1:
            raise LinguaError(
                ErrorCode.MODEL_API,
                "Synthetic retryable failure",
                retryable=True,
            )
        return TranslationResult(f"[fr] {request.text}", "flaky-v1")


def _controlled_job(service: ApplicationService, provider: TranslationProvider) -> dict:
    service.providers = ProviderRegistry([provider])
    project = service.create_project(
        name="Controlled novel",
        kind="novel",
        source_language="en",
        target_language="de",
        source_name="controlled.txt",
        source_bytes=b"First segment.\n\nSecond segment.",
    )
    return service.create_job(project_id=project["id"], provider_id=provider.id)


def test_pause_and_resume_reuses_completed_segments(service: ApplicationService) -> None:
    provider = ControlledProvider()
    job = _controlled_job(service, provider)
    runner = JobRunner(service)
    runner.start(recover=False)
    try:
        assert provider.entered.wait(5)
        pausing = service.pause_job(job["id"])
        assert pausing["status"] == "running"
        assert pausing["control_request"] == "pause"

        provider.release.set()
        paused = _wait_for_status(service, job["id"], {"paused"})
        translate = next(step for step in paused["steps"] if step["key"] == "translate_text")
        assert translate["status"] == "paused"
        assert translate["attempt_count"] == 1
        segments = service.list_segments(job["project_id"], job_id=job["id"])
        assert [segment["status"] for segment in segments] == ["succeeded", "pending"]

        resumed = service.resume_job(job["id"])
        assert resumed["status"] == "queued"
        completed = _wait_for_status(service, job["id"], {"succeeded"})
        translate = next(step for step in completed["steps"] if step["key"] == "translate_text")
        assert translate["attempt_count"] == 2
        assert provider.calls == 2
        assert all(
            segment["status"] == "succeeded"
            for segment in service.list_segments(job["project_id"], job_id=job["id"])
        )
    finally:
        provider.release.set()
        runner.stop()


def test_cancel_stays_cancelling_until_a_safe_boundary(service: ApplicationService) -> None:
    provider = ControlledProvider()
    job = _controlled_job(service, provider)
    runner = JobRunner(service)
    runner.start(recover=False)
    try:
        assert provider.entered.wait(5)
        cancelling = service.cancel_job(job["id"])
        assert cancelling["status"] == "cancelling"
        assert cancelling["control_request"] == "cancel"
        assert not provider.completed.is_set()

        provider.release.set()
        cancelled = _wait_for_status(service, job["id"], {"cancelled"})
        assert provider.completed.is_set()
        assert cancelled["error"]["code"] == ErrorCode.CANCELLED
        assert not {
            "pending",
            "running",
            "paused",
            "cancelling",
        } & {step["status"] for step in cancelled["steps"]}
        translate = next(step for step in cancelled["steps"] if step["key"] == "translate_text")
        assert translate["status"] == "cancelled"
        assert all(
            step["status"] == "cancelled"
            for step in cancelled["steps"]
            if step["order"] > translate["order"]
        )
    finally:
        provider.release.set()
        runner.stop()


def test_failed_segment_retry_preserves_success_and_attempt_history(
    service: ApplicationService,
) -> None:
    provider = FlakyProvider()
    service.providers = ProviderRegistry([provider])
    project = service.create_project(
        name="Retry novel",
        kind="novel",
        source_language="en",
        target_language="fr",
        source_name="retry.txt",
        source_bytes=b"already-good\n\nretry-me",
    )
    job = service.create_job(project_id=project["id"], provider_id=provider.id)
    runner = JobRunner(service)

    assert runner.run_once() is True
    partial = service.get_job(job["id"])
    assert partial["status"] == "partially_succeeded"
    assert [segment["status"] for segment in service.list_segments(project["id"])] == [
        "succeeded",
        "failed",
    ]
    first_attempts = {step["key"]: step["attempt_count"] for step in partial["steps"]}

    retried = service.retry_job(job["id"])
    assert retried["status"] == "queued"
    assert runner.run_once() is True
    completed = service.get_job(job["id"])
    assert completed["status"] == "succeeded"
    assert provider.calls["already-good"] == 1
    assert provider.calls["retry-me"] == 2
    attempts = {step["key"]: step["attempt_count"] for step in completed["steps"]}
    assert attempts["segment_text"] == first_attempts["segment_text"]
    assert attempts["translate_text"] == first_attempts["translate_text"] + 1
    assert attempts["quality_check"] == first_attempts["quality_check"] + 1
    translate = next(step for step in completed["steps"] if step["key"] == "translate_text")
    assert any(log["message"] == "Step scheduled for retry" for log in translate["logs"])
