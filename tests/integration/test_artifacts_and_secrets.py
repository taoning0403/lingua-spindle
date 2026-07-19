from __future__ import annotations

import hashlib
import json

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


class LeakyProvider(TranslationProvider):
    id = "leaky-test"
    display_name = "Leaky test Provider"

    def __init__(self, secret: str) -> None:
        self.secret = secret

    def configured(self) -> bool:
        return True

    def public_status(self) -> dict:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "configured": True,
            "model": self.secret,
            "diagnostic": self.secret,
        }

    def translate(self, _request: TranslationRequest) -> TranslationResult:
        raise LinguaError(
            ErrorCode.MODEL_API,
            f"Provider echoed {self.secret}",
            {"body": self.secret, "api_key": "another-secret"},
            retryable=True,
        )


def test_artifact_provenance_checksum_immutability_and_safe_paths(
    service: ApplicationService,
) -> None:
    source_payload = b"First.\n\nSecond."
    project = service.create_project(
        name="Artifact novel",
        kind="novel",
        source_language="en",
        target_language="it",
        source_name="artifact.txt",
        source_bytes=source_payload,
    )
    source = service.source_artifact(project["id"])
    assert source.checksum == hashlib.sha256(source_payload).hexdigest()

    job = service.create_job(project_id=project["id"])
    assert JobRunner(service).run_once() is True
    completed = service.get_job(job["id"])
    artifacts = service.list_artifacts(project_id=project["id"])
    by_id = {artifact["id"]: artifact for artifact in artifacts}
    for step in completed["steps"]:
        for artifact_id in step["input_artifact_ids"]:
            assert artifact_id in by_id
        for artifact_id in step["output_artifact_ids"]:
            assert by_id[artifact_id]["step_run_id"] == step["id"]
            assert by_id[artifact_id]["job_id"] == job["id"]

    _, unchanged = service.read_artifact(source.id)
    assert unchanged == source_payload
    with pytest.raises(LinguaError) as traversal:
        service.store.read_bytes("../outside")
    assert traversal.value.code == ErrorCode.STORAGE
    with pytest.raises(LinguaError) as absolute:
        service.store.read_bytes(str(service.settings.data_dir.anchor) + "outside")
    assert absolute.value.code == ErrorCode.STORAGE


def test_failed_artifact_metadata_publication_removes_payload(
    service: ApplicationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = service.create_project(
        name="Atomic novel",
        kind="novel",
        source_language="en",
        target_language="de",
        source_name="atomic.txt",
        source_bytes=b"Atomic.",
    )
    before = {path for path in service.store.root.rglob("*") if path.is_file()}

    class BrokenSession:
        def __enter__(self):
            raise RuntimeError("synthetic database failure")

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(service.database, "session", lambda: BrokenSession())
    with pytest.raises(RuntimeError, match="synthetic database failure"):
        service.create_artifact(
            project_id=project["id"],
            kind="test",
            filename="atomic.bin",
            media_type="application/octet-stream",
            payload=b"must be removed",
        )
    after = {path for path in service.store.root.rglob("*") if path.is_file()}
    assert after == before


def test_project_deletion_requires_confirmation_and_removes_metadata_and_payloads(
    service: ApplicationService,
) -> None:
    project = service.create_project(
        name="Delete novel",
        kind="novel",
        source_language="en",
        target_language="fr",
        source_name="delete.txt",
        source_bytes=b"Delete me.",
    )
    source = service.source_artifact(project["id"])
    payload_path = service.store.path_for_adapter(source.storage_key)
    assert payload_path.is_file()

    with pytest.raises(LinguaError) as confirmation:
        service.delete_project(project["id"], confirmed=False)
    assert confirmation.value.code == ErrorCode.INVALID_STATE
    assert confirmation.value.details == {"impact": {"sources": 1, "jobs": 0, "artifacts": 1}}

    deleted = service.delete_project(project["id"], confirmed=True)
    assert deleted["deleted"] == project["id"]
    assert deleted["cleanup_error"] is None
    assert not payload_path.exists()
    with pytest.raises(LinguaError) as missing:
        service.get_project(project["id"])
    assert missing.value.code == ErrorCode.NOT_FOUND


def test_runtime_provider_key_never_reaches_database_logs_artifacts_or_exports(tmp_path) -> None:
    runtime_value = "sk-" + "unique-runtime-key-97cbb40b"
    settings = Settings(data_dir=tmp_path / "secure-data", openai_api_key=runtime_value)
    service = ApplicationService(settings)
    try:
        provider = LeakyProvider(runtime_value)
        service.providers = ProviderRegistry([provider])
        project = service.create_project(
            name="Secure novel",
            kind="novel",
            source_language="en",
            target_language="fr",
            source_name="secure.txt",
            source_bytes=b"No secret in this source.",
        )
        profile = service.create_profile(
            name="Secret-safe profile",
            source_language="en",
            target_language="fr",
            provider_id=provider.id,
            style=f"Never serialize {runtime_value}",
            prompt_template=f"Translate {{text}} while hiding {runtime_value}",
            model_parameters={"api_key": "another-secret", "diagnostic": runtime_value},
        )
        assert runtime_value not in json.dumps(profile)
        assert profile["model_parameters"]["api_key"] == "[REDACTED]"
        assert runtime_value not in json.dumps(service.provider_statuses())

        job = service.create_job(project_id=project["id"], profile_id=profile["id"])
        assert JobRunner(service).run_once() is True
        completed = service.get_job(job["id"])
        assert completed["status"] == "partially_succeeded"
        translate = next(step for step in completed["steps"] if step["key"] == "translate_text")
        service.add_log(
            translate["id"],
            "ERROR",
            f"Authorization: Bearer {runtime_value}",
            {"response": runtime_value, "api_key": "another-secret"},
        )
        raw = service.create_artifact(
            project_id=project["id"],
            job_id=job["id"],
            step_run_id=translate["id"],
            kind="security_probe",
            filename=f"probe-{runtime_value}.json",
            media_type="application/json",
            payload=json.dumps({"api_key": "another-secret", "message": runtime_value}).encode(),
            metadata={"authorization": runtime_value, "message": runtime_value},
        )
        metadata, payload = service.read_artifact(raw.id)
        assert runtime_value not in json.dumps(metadata)
        assert runtime_value.encode() not in payload
        assert b"[REDACTED]" in payload

        public_state = {
            "job": service.get_job(job["id"]),
            "segments": service.list_segments(project["id"], job_id=job["id"]),
            "artifacts": service.list_artifacts(project_id=project["id"]),
            "exports": service.export_project(project["id"]),
        }
        assert runtime_value not in json.dumps(public_state)
    finally:
        service.close()

    contaminated = [
        str(path)
        for path in settings.data_dir.rglob("*")
        if path.is_file() and runtime_value.encode() in path.read_bytes()
    ]
    assert contaminated == []


def test_import_rejects_the_active_runtime_provider_key(tmp_path) -> None:
    runtime_value = "sk-" + "do-not-import"
    service = ApplicationService(Settings(data_dir=tmp_path / "data", openai_api_key=runtime_value))
    try:
        with pytest.raises(LinguaError) as caught:
            service.create_project(
                name="Unsafe source",
                kind="novel",
                source_language="en",
                target_language="fr",
                source_name="unsafe.txt",
                source_bytes=f"Accidentally pasted {runtime_value}".encode(),
            )
        assert caught.value.code == ErrorCode.CONFIGURATION
        assert runtime_value not in caught.value.message
    finally:
        service.close()
