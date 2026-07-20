from __future__ import annotations

from linguaspindle.application import ApplicationService
from linguaspindle.config import Settings
from linguaspindle.errors import ErrorCode
from linguaspindle.orchestration.engine import JobRunner


def test_startup_recovery_marks_active_step_failed_and_allows_retry(tmp_path) -> None:
    settings = Settings.from_env(tmp_path / "persistent-data")
    first = ApplicationService(settings)
    project = first.create_project(
        name="Interrupted novel",
        kind="novel",
        source_language="en",
        target_language="es",
        source_name="interrupted.txt",
        source_bytes=b"Persist me.",
    )
    job = first.create_job(project_id=project["id"])
    assert first.claim_next_job("crashed-runner") == job["id"]
    first_step = first.get_job(job["id"])["steps"][0]
    first.start_step(first_step["id"])
    source_artifact = first.source_artifact(project["id"])
    first.replace_segments(
        project_id=project["id"],
        job_id=job["id"],
        profile=job["profile_snapshot"],
        segments=[
            {
                "source_text": "Persist me.",
                "source_artifact_id": source_artifact.id,
                "source_document": "OPS/chapter.xhtml",
                "content_role": "xhtml",
                "locator": {"document_path": "OPS/chapter.xhtml", "element_index": 2},
                "source_text_hash": "synthetic-source-hash",
                "translation_input_hash": "synthetic-input-hash",
            }
        ],
    )
    interrupted_segment = first.segment_rows(job["id"])[0]
    first.update_segment(interrupted_segment.id, status="running")
    first.close()

    second = ApplicationService(settings)
    try:
        assert second.recover_interrupted_jobs() == 1
        recovered = second.get_job(job["id"])
        assert recovered["status"] == "failed"
        assert recovered["error"]["code"] == ErrorCode.PROCESS_INTERRUPTED
        interrupted = recovered["steps"][0]
        assert interrupted["status"] == "failed"
        assert interrupted["error"]["code"] == ErrorCode.PROCESS_INTERRUPTED
        assert any("restart interrupted" in log["message"] for log in interrupted["logs"])
        recovered_segments = second.list_segments(project["id"], job_id=job["id"])
        assert recovered_segments[0]["status"] == "failed"
        assert recovered_segments[0]["error"]["code"] == ErrorCode.PROCESS_INTERRUPTED
        assert recovered_segments[0]["source_document"] == "OPS/chapter.xhtml"

        second.retry_job(job["id"])
        assert JobRunner(second).run_once() is True
        completed = second.get_job(job["id"])
        assert completed["status"] == "succeeded"
        assert completed["steps"][0]["attempt_count"] == 2
        assert all(step["status"] == "succeeded" for step in completed["steps"])
    finally:
        second.close()


def test_unexpected_pipeline_boundary_failure_is_normalized(service, monkeypatch) -> None:
    project = service.create_project(
        name="Boundary failure",
        kind="novel",
        source_language="en",
        target_language="fr",
        source_name="boundary.txt",
        source_bytes=b"Boundary.",
    )
    job = service.create_job(project_id=project["id"])
    runner = JobRunner(service)

    def fail_before_step(*_args, **_kwargs):
        raise RuntimeError("untrusted detail must not escape")

    monkeypatch.setattr(runner, "_input_artifacts", fail_before_step)
    assert runner.run_once() is True
    failed = service.get_job(job["id"])
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == ErrorCode.UNKNOWN
    assert failed["error"]["details"] == {"exception_type": "RuntimeError"}
    assert "untrusted detail" not in str(failed)


def test_runner_tolerates_a_claimed_job_removed_by_an_external_race(service) -> None:
    runner = JobRunner(service)

    runner._execute("job-that-no-longer-exists")

    project = service.create_project(
        name="Runner remains usable",
        kind="novel",
        source_language="en",
        target_language="fr",
        source_name="runner.txt",
        source_bytes=b"Still runs.",
    )
    job = service.create_job(project_id=project["id"])
    assert runner.run_once() is True
    assert service.get_job(job["id"])["status"] == "succeeded"
