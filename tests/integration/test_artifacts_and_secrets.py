from __future__ import annotations

import hashlib
import io
import json
import zipfile

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


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"])
def test_import_rejects_runtime_key_in_common_wide_text_encodings(tmp_path, encoding: str) -> None:
    runtime_value = "sk-wide-text-do-not-import"
    service = ApplicationService(
        Settings(data_dir=tmp_path / encoding, openai_api_key=runtime_value)
    )
    try:
        with pytest.raises(LinguaError) as caught:
            service.create_project(
                name="Wide text secret",
                kind="novel",
                source_language="en",
                target_language="fr",
                source_name="wide.txt",
                source_bytes=f"Accidentally pasted {runtime_value}".encode(encoding),
            )
        assert caught.value.code == ErrorCode.CONFIGURATION
        assert service.list_projects() == []
    finally:
        service.close()


def _compressed_epub_with_secret(secret: str, location: str) -> bytes:
    title = secret if location == "metadata" else "Safe title"
    paragraph = secret if location == "body" else "Safe paragraph"
    script = secret if location == "script" else "safe-script-value"
    package = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">
  <metadata><dc:identifier>fixture</dc:identifier><dc:title>{title}</dc:title>
    <dc:language>en</dc:language></metadata>
  <manifest>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine><itemref idref="chapter"/></spine>
</package>""".encode()
    chapter = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter</title>
  <script>{script}</script></head><body><p>{paragraph}</p></body></html>""".encode()
    container = b"""<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OPS/content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    nav = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title>Navigation</title></head><body>
    <nav epub:type="toc"><ol><li><a href="chapter.xhtml">Chapter</a></li></ol></nav>
  </body>
</html>"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/content.opf", package)
        archive.writestr("OPS/chapter.xhtml", chapter)
        archive.writestr("OPS/nav.xhtml", nav)
    return output.getvalue()


@pytest.mark.parametrize("location", ["metadata", "body", "script"])
def test_import_rejects_runtime_key_inside_compressed_epub_members(tmp_path, location: str) -> None:
    runtime_value = f"sk-compressed-{location}-97cbb40b"
    payload = _compressed_epub_with_secret(runtime_value, location)
    assert runtime_value.encode() not in payload
    settings = Settings(data_dir=tmp_path / f"compressed-{location}", openai_api_key=runtime_value)
    service = ApplicationService(settings)
    try:
        with pytest.raises(LinguaError) as caught:
            service.create_project(
                name="Compressed secret fixture",
                kind="novel",
                source_language="en",
                target_language="fr",
                source_name="compressed.epub",
                source_bytes=payload,
                media_type="application/epub+zip",
            )
        assert caught.value.code == ErrorCode.CONFIGURATION
        assert service.list_projects() == []
    finally:
        service.close()

    assert all(
        runtime_value.encode() not in path.read_bytes()
        for path in settings.data_dir.rglob("*")
        if path.is_file()
    )


def test_user_prose_with_secret_shaped_words_is_preserved(service: ApplicationService) -> None:
    prose = "The password: castle is a clue; secret=plot is ordinary prose."
    project = service.create_project(
        name="The password: castle project",
        kind="novel",
        source_language="en",
        target_language="fr",
        source_name="secret=plot.txt",
        source_bytes=prose.encode(),
    )
    profile = service.create_profile(
        name="The password: castle profile",
        source_language="en",
        target_language="fr",
        provider_id="mock",
        style="Keep secret=plot and password: castle literally.",
        prompt_template="Translate {text}; password: castle and secret=plot are content.",
    )
    assert project["name"] == "The password: castle project"
    assert profile["style"] == "Keep secret=plot and password: castle literally."

    job = service.create_job(project_id=project["id"], profile_id=profile["id"])
    assert JobRunner(service).run_once() is True
    assert service.get_job(job["id"])["status"] == "succeeded"
    segments = service.list_segments(project["id"], job_id=job["id"])
    assert segments[0]["source_text"] == prose
    assert prose in segments[0]["translated_text"]

    content_kinds = {
        "novel_text_extracted",
        "novel_segments",
        "novel_translations",
        "novel_export_txt",
        "novel_export_json",
    }
    for artifact in service.list_artifacts(project_id=project["id"], job_id=job["id"]):
        if artifact["kind"] not in content_kinds:
            continue
        _, artifact_payload = service.read_artifact(artifact["id"])
        assert b"[REDACTED]" not in artifact_payload
        if artifact["kind"] != "novel_segments":
            assert b"password: castle" in artifact_payload


def test_project_with_active_job_must_be_cancelled_before_deletion(
    service: ApplicationService,
) -> None:
    project = service.create_project(
        name="Active deletion guard",
        kind="novel",
        source_language="en",
        target_language="fr",
        source_name="active.txt",
        source_bytes=b"Active job.",
    )
    job = service.create_job(project_id=project["id"])

    with pytest.raises(LinguaError) as active:
        service.delete_project(project["id"], confirmed=True)
    assert active.value.code == ErrorCode.INVALID_STATE
    assert active.value.details == {"active_jobs": [{"id": job["id"], "status": "queued"}]}

    service.cancel_job(job["id"])
    assert service.delete_project(project["id"], confirmed=True)["deleted"] == project["id"]
