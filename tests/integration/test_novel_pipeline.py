from __future__ import annotations

import pytest

from linguaspindle.application import ApplicationService
from linguaspindle.config import Settings
from linguaspindle.errors import ErrorCode, LinguaError
from linguaspindle.orchestration.engine import JobRunner


def test_mock_txt_pipeline_persists_and_exports(service: ApplicationService) -> None:
    project = service.create_project(
        name="A small novel",
        kind="novel",
        source_language="en",
        target_language="zh-CN",
        source_name="novel.txt",
        source_bytes=b"Chapter 1\n\nHello world.\n\nGoodbye.",
        media_type="text/plain",
    )
    job = service.create_job(project_id=project["id"], provider_id="mock")

    runner = JobRunner(service)
    assert runner.run_once() is True

    completed = service.get_job(job["id"])
    assert completed["status"] == "succeeded"
    assert completed["progress"] == 1.0
    assert all(step["status"] == "succeeded" for step in completed["steps"])

    segments = service.list_segments(project["id"], job_id=job["id"])
    assert [segment["sequence"] for segment in segments] == [0, 1, 2]
    assert all(segment["translated_text"].startswith("[zh-CN]") for segment in segments)

    artifacts = service.list_artifacts(project_id=project["id"], job_id=job["id"])
    kinds = {artifact["kind"] for artifact in artifacts}
    assert {"novel_export_txt", "novel_export_json", "qa_report"} <= kinds
    txt = next(item for item in artifacts if item["kind"] == "novel_export_txt")
    _, payload = service.read_artifact(txt["id"])
    assert b"[zh-CN]" in payload


def test_restart_keeps_completed_steps(tmp_path) -> None:
    settings = Settings.from_env(tmp_path / "data")
    first = ApplicationService(settings)
    project = first.create_project(
        name="Restart novel",
        kind="novel",
        source_language="en",
        target_language="fr",
        source_name="restart.txt",
        source_bytes=b"One paragraph.",
    )
    job = first.create_job(project_id=project["id"])
    JobRunner(first).run_once()
    attempts = [step["attempt_count"] for step in first.get_job(job["id"])["steps"]]
    first.close()

    second = ApplicationService(settings)
    try:
        persisted = second.get_job(job["id"])
        assert persisted["status"] == "succeeded"
        assert [step["attempt_count"] for step in persisted["steps"]] == attempts
        assert second.recover_interrupted_jobs() == 0
    finally:
        second.close()


def test_project_result_view_defaults_to_latest_job(service: ApplicationService) -> None:
    project = service.create_project(
        name="Rerun novel",
        kind="novel",
        source_language="en",
        target_language="fr",
        source_name="rerun.txt",
        source_bytes=b"One.\n\nTwo.",
    )
    first = service.create_job(project_id=project["id"])
    assert JobRunner(service).run_once() is True
    second = service.create_job(project_id=project["id"])
    assert JobRunner(service).run_once() is True

    assert {segment["job_id"] for segment in service.list_segments(project["id"])} == {second["id"]}
    assert {
        segment["job_id"] for segment in service.list_segments(project["id"], job_id=first["id"])
    } == {first["id"]}


def test_job_rejects_missing_or_language_mismatched_profile(
    service: ApplicationService,
) -> None:
    project = service.create_project(
        name="Profile validation",
        kind="novel",
        source_language="en",
        target_language="fr",
        source_name="profile.txt",
        source_bytes=b"Validate profile.",
    )
    with pytest.raises(LinguaError) as missing:
        service.create_job(project_id=project["id"], profile_id="missing-profile")
    assert missing.value.code == ErrorCode.NOT_FOUND

    mismatch = service.create_profile(
        name="Wrong language pair",
        source_language="ja",
        target_language="en",
        provider_id="mock",
    )
    with pytest.raises(LinguaError) as invalid:
        service.create_job(project_id=project["id"], profile_id=mismatch["id"])
    assert invalid.value.code == ErrorCode.CONFIGURATION
