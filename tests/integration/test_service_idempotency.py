from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import httpx
import pytest

from linguaspindle.application import ApplicationService
from linguaspindle.config import Settings
from linguaspindle.errors import ErrorCode, LinguaError
from linguaspindle.idempotency import IdempotencyContext, idempotency_context
from linguaspindle.interfaces.api import (
    TranslateSegmentsRequest,
    _translate_selected_segments,
    create_app,
)
from linguaspindle.orchestration.engine import JobRunner
from linguaspindle.providers.base import (
    ProviderRegistry,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)


def _context(key: str, request_id: str = "request-test-0001") -> IdempotencyContext:
    context = idempotency_context(key, request_id=request_id, required=True)
    assert context is not None
    return context


def _project_operation(
    service: ApplicationService,
    context: IdempotencyContext,
    *,
    payload: bytes = b"First.\n\nSecond.",
):
    return service.create_project_from_stream_operation(
        name="Idempotent project",
        kind="novel",
        source_language="en",
        target_language="fr",
        source_name="source.txt",
        source=BytesIO(payload),
        media_type="text/plain",
        idempotency=context,
    )


def _row_count(settings: Settings, table: str) -> int:
    statements = {
        "artifacts": "SELECT COUNT(*) FROM artifacts",
        "jobs": "SELECT COUNT(*) FROM jobs",
        "projects": "SELECT COUNT(*) FROM projects",
        "sources": "SELECT COUNT(*) FROM sources",
        "step_runs": "SELECT COUNT(*) FROM step_runs",
    }
    with sqlite3.connect(settings.database_path) as connection:
        return int(connection.execute(statements[table]).fetchone()[0])


def test_project_key_replays_conflicts_and_never_retains_raw_key(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(data_dir=tmp_path / "project-idempotency")
    service = ApplicationService(settings)
    raw_key = "novel-platform:project-key-0001"
    context = _context(raw_key)
    try:
        first = _project_operation(service, context)
        replay = _project_operation(service, _context(raw_key, "request-test-0002"))

        assert first.replayed is False
        assert replay.replayed is True
        assert replay.value["id"] == first.value["id"]
        assert _row_count(settings, "projects") == 1
        assert _row_count(settings, "sources") == 1
        assert _row_count(settings, "artifacts") == 1

        with pytest.raises(LinguaError) as conflict:
            _project_operation(
                service,
                _context(raw_key, "request-test-0003"),
                payload=b"Different source bytes.",
            )
        assert conflict.value.code == ErrorCode.IDEMPOTENCY_CONFLICT

        persisted = settings.data_dir.read_bytes() if settings.data_dir.is_file() else b""
        persisted += b"".join(
            path.read_bytes() for path in settings.data_dir.rglob("*") if path.is_file()
        )
        assert raw_key.encode() not in persisted
        assert raw_key not in caplog.text
        with sqlite3.connect(settings.database_path) as connection:
            stored_hash = connection.execute("SELECT key_hash FROM idempotency_records").fetchone()[
                0
            ]
        assert stored_hash == hashlib.sha256(raw_key.encode()).hexdigest()
    finally:
        service.close()


def test_completed_project_key_survives_service_restart(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "project-restart")
    context = _context("novel-platform:project-restart-0001")
    first = ApplicationService(settings)
    created = _project_operation(first, context)
    first.close()

    second = ApplicationService(settings)
    try:
        replay = _project_operation(second, context)
        assert replay.replayed is True
        assert replay.value["id"] == created.value["id"]
        assert _row_count(settings, "projects") == 1
    finally:
        second.close()


@pytest.mark.parametrize("shared_service", [True, False])
def test_concurrent_project_requests_publish_one_project_and_no_orphan_payload(
    tmp_path: Path,
    shared_service: bool,
) -> None:
    settings = Settings(data_dir=tmp_path / f"project-race-{shared_service}")
    first = ApplicationService(settings)
    second = first if shared_service else ApplicationService(settings)
    barrier = threading.Barrier(2)
    context = _context("novel-platform:project-race-0001")

    def create(service: ApplicationService):
        barrier.wait(timeout=5)
        return _project_operation(service, context)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, (first, second)))
        assert {result.value["id"] for result in results} == {results[0].value["id"]}
        assert sorted(result.replayed for result in results) == [False, True]
        assert _row_count(settings, "projects") == 1
        assert _row_count(settings, "sources") == 1
        assert _row_count(settings, "artifacts") == 1
        payloads = [
            path
            for path in settings.artifacts_dir.rglob("*")
            if path.is_file() and not path.name.startswith(".pending-")
        ]
        assert len(payloads) == 1
        assert not list(settings.artifacts_dir.rglob(".pending-*"))
    finally:
        if second is not first:
            second.close()
        first.close()


@pytest.mark.parametrize("shared_service", [True, False])
def test_active_job_fingerprint_coalesces_concurrent_services_and_terminal_reruns(
    tmp_path: Path,
    shared_service: bool,
) -> None:
    settings = Settings(data_dir=tmp_path / f"job-race-{shared_service}")
    first = ApplicationService(settings)
    project = first.create_project(
        name="Job coalescing",
        kind="novel",
        source_language="en",
        target_language="fr",
        source_name="job.txt",
        source_bytes=b"Translate once.",
    )
    second = first if shared_service else ApplicationService(settings)
    barrier = threading.Barrier(2)

    def create(arguments: tuple[ApplicationService, str]):
        service, key = arguments
        barrier.wait(timeout=5)
        return service.create_job_operation(
            project_id=project["id"],
            idempotency=_context(key),
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    create,
                    (
                        (first, "novel-platform:job-race-key-0001"),
                        (second, "novel-platform:job-race-key-0002"),
                    ),
                )
            )
        assert {result.value["id"] for result in results} == {results[0].value["id"]}
        assert sorted(result.coalesced for result in results) == [False, True]
        assert _row_count(settings, "jobs") == 1
        assert _row_count(settings, "step_runs") == len(results[0].value["steps"])

        original_job_id = results[0].value["id"]
        assert JobRunner(first).run_once() is True
        assert first.get_job(original_job_id)["status"] == "succeeded"

        rerun = first.create_job_operation(
            project_id=project["id"],
            idempotency=_context("novel-platform:job-rerun-key-0003"),
        )
        old_key = first.create_job_operation(
            project_id=project["id"],
            idempotency=_context("novel-platform:job-race-key-0001"),
        )
        assert rerun.value["id"] != original_job_id
        assert rerun.coalesced is False
        assert old_key.value["id"] == original_job_id
        assert old_key.replayed is True
    finally:
        if second is not first:
            second.close()
        first.close()


def test_same_job_key_with_different_effective_profile_conflicts(tmp_path: Path) -> None:
    service = ApplicationService(Settings(data_dir=tmp_path / "job-conflict"))
    try:
        project = service.create_project(
            name="Job conflict",
            kind="novel",
            source_language="en",
            target_language="fr",
            source_name="source.txt",
            source_bytes=b"Conflict.",
        )
        key = _context("novel-platform:job-conflict-key-0001")
        service.create_job_operation(project_id=project["id"], idempotency=key)
        profile = service.create_profile(
            name="Different profile",
            source_language="en",
            target_language="fr",
            provider_id="mock",
            style="Use deliberately different style guidance.",
        )
        with pytest.raises(LinguaError) as conflict:
            service.create_job_operation(
                project_id=project["id"],
                profile_id=profile["id"],
                idempotency=key,
            )
        assert conflict.value.code == ErrorCode.IDEMPOTENCY_CONFLICT
        assert _row_count(service.settings, "jobs") == 1
    finally:
        service.close()


class CountingProvider(TranslationProvider):
    id = "counting"

    def __init__(self) -> None:
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False

    def public_status(self) -> dict[str, object]:
        return {"id": self.id, "configured": True, "model": "counting-v1"}

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls += 1
        self.entered.set()
        if self.block and not self.release.wait(5):
            raise RuntimeError("counting provider test timeout")
        return TranslationResult(text=f"[fr] {request.text}", model="counting-v1")


async def _selected_translation_flow(data_dir: Path) -> None:
    application = create_app(Settings(data_dir=data_dir), start_worker=False)
    async with application.router.lifespan_context(application):
        provider = CountingProvider()
        application.state.service.providers = ProviderRegistry([provider])
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/projects",
                headers={
                    "Idempotency-Key": "novel-platform:selected-project-0001",
                    "X-Request-ID": "request-selected-project-0001",
                },
                data={
                    "name": "Selected idempotency",
                    "kind": "novel",
                    "source_language": "en",
                    "target_language": "fr",
                },
                files={"source": ("source.txt", b"Only once.", "text/plain")},
            )
            assert created.status_code == 201
            assert created.headers["Idempotency-Replayed"] == "false"
            assert created.headers["Location"].endswith(created.json()["id"])
            project_id = created.json()["id"]
            segment_id = (await client.get(f"/api/projects/{project_id}/segments")).json()[0][
                "segment_id"
            ]
            url = f"/api/projects/{project_id}/segments/translate"
            headers = {"Idempotency-Key": "novel-platform:selected-key-0001"}
            body = {"provider_id": "counting", "selected_segment_ids": [segment_id]}

            first = await client.post(url, headers=headers, json=body)
            replay = await client.post(url, headers=headers, json=body)
            assert first.status_code == replay.status_code == 200
            assert first.headers["Idempotency-Replayed"] == "false"
            assert replay.headers["Idempotency-Replayed"] == "true"
            assert first.json()["artifact"]["id"] == replay.json()["artifact"]["id"]
            assert provider.calls == 1

            conflict = await client.post(
                url,
                headers=headers,
                json={**body, "style": "Different"},
            )
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

            provider.block = True
            race_headers = {"Idempotency-Key": "novel-platform:selected-race-0002"}
            first_task = asyncio.create_task(client.post(url, headers=race_headers, json=body))
            assert await asyncio.to_thread(provider.entered.wait, 5)
            in_progress = await client.post(url, headers=race_headers, json=body)
            assert in_progress.status_code == 409
            assert in_progress.json()["error"]["code"] == "IDEMPOTENCY_IN_PROGRESS"
            assert in_progress.headers["Retry-After"] == "1"
            provider.release.set()
            completed = await first_task
            assert completed.status_code == 200
            assert provider.calls == 2


def test_selected_translation_replay_and_asgi_concurrency_call_provider_once(
    tmp_path: Path,
) -> None:
    asyncio.run(_selected_translation_flow(tmp_path / "selected-api"))


async def _rebuild_replay_flow(data_dir: Path) -> None:
    application = create_app(Settings(data_dir=data_dir), start_worker=False)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/projects",
                data={
                    "name": "Rebuild replay",
                    "kind": "novel",
                    "source_language": "en",
                    "target_language": "fr",
                },
                files={"source": ("source.txt", b"Rebuild once.", "text/plain")},
            )
            project_id = created.json()["id"]
            segment_id = (await client.get(f"/api/projects/{project_id}/segments")).json()[0][
                "segment_id"
            ]
            url = f"/api/projects/{project_id}/rebuild"
            headers = {"Idempotency-Key": "novel-platform:rebuild-key-0001"}
            body = {"translations": {segment_id: "Reconstruit une fois."}}

            first = await client.post(url, headers=headers, json=body)
            replay = await client.post(url, headers=headers, json=body)
            assert first.status_code == replay.status_code == 200
            assert first.headers["Idempotency-Replayed"] == "false"
            assert replay.headers["Idempotency-Replayed"] == "true"
            assert first.json()["artifact"]["id"] == replay.json()["artifact"]["id"]
            assert first.headers["Location"].endswith(first.json()["artifact"]["id"])
            artifacts = await client.get(f"/api/projects/{project_id}/artifacts")
            assert sum(item["kind"] == "novel_export_txt" for item in artifacts.json()) == 1

            conflict = await client.post(
                url,
                headers=headers,
                json={"translations": {segment_id: "Different text."}},
            )
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_rebuild_replay_does_not_create_duplicate_artifact(tmp_path: Path) -> None:
    asyncio.run(_rebuild_replay_flow(tmp_path / "rebuild-api"))


class InterruptingProvider(TranslationProvider):
    id = "interrupting"

    def public_status(self) -> dict[str, object]:
        return {"id": self.id, "configured": True, "model": "interrupting-v1"}

    def translate(self, request: TranslationRequest) -> TranslationResult:
        raise KeyboardInterrupt


def test_interrupted_selected_translation_becomes_indeterminate(tmp_path: Path) -> None:
    service = ApplicationService(Settings(data_dir=tmp_path / "indeterminate"))
    try:
        service.providers = ProviderRegistry([InterruptingProvider()])
        project = service.create_project(
            name="Indeterminate",
            kind="novel",
            source_language="en",
            target_language="fr",
            source_name="source.txt",
            source_bytes=b"Potential provider cost.",
        )
        from linguaspindle.interfaces.api import _novel_source_context

        source_context = _novel_source_context(service, project["id"])
        segment_id = source_context.manifest.segments[0].segment_id
        body = TranslateSegmentsRequest(
            provider_id="interrupting",
            selected_segment_ids=[segment_id],
        )
        context = _context("novel-platform:indeterminate-key-0001")
        with pytest.raises(KeyboardInterrupt):
            _translate_selected_segments(service, project["id"], body, context)

        with sqlite3.connect(service.settings.database_path) as connection:
            status = connection.execute(
                "SELECT status FROM idempotency_records WHERE scope LIKE '%segments:translate'"
            ).fetchone()[0]
        assert status == "indeterminate"

        with pytest.raises(LinguaError) as replay:
            _translate_selected_segments(service, project["id"], body, context)
        assert replay.value.code == ErrorCode.IDEMPOTENCY_INDETERMINATE
    finally:
        service.close()


async def _configuration_and_request_id_flow(data_dir: Path) -> None:
    settings = Settings(data_dir=data_dir, require_idempotency_key=True)
    application = create_app(settings, start_worker=False)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            fields = {
                "name": "Required key",
                "kind": "novel",
                "source_language": "en",
                "target_language": "fr",
            }
            missing = await client.post(
                "/api/projects",
                data=fields,
                files={"source": ("source.txt", b"Required.", "text/plain")},
            )
            assert missing.status_code == 428
            assert missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
            assert "X-Request-ID" in missing.headers

            invalid = await client.post(
                "/api/projects",
                headers={"Idempotency-Key": "bad!key", "X-Request-ID": "unsafe request id!"},
                data=fields,
                files={"source": ("source.txt", b"Required.", "text/plain")},
            )
            assert invalid.status_code == 400
            assert invalid.json()["error"]["code"] == "IDEMPOTENCY_KEY_INVALID"
            assert invalid.headers["X-Request-ID"] != "unsafe request id!"

            valid_request_id = "request-valid-0001"
            created = await client.post(
                "/api/projects",
                headers={
                    "Idempotency-Key": "novel-platform:required-key-0001",
                    "X-Request-ID": valid_request_id,
                },
                data=fields,
                files={"source": ("source.txt", b"Required.", "text/plain")},
            )
            assert created.status_code == 201
            assert created.headers["X-Request-ID"] == valid_request_id

            system = await client.get("/api/system")
            assert system.json()["require_idempotency_key"] is True
            document = (await client.get("/openapi.json")).json()
            project_operation = document["paths"]["/api/projects"]["post"]
            assert any(
                parameter["name"] == "Idempotency-Key"
                for parameter in project_operation["parameters"]
            )
            assert "428" in project_operation["responses"]
            assert "Idempotency-Replayed" in project_operation["responses"]["201"]["headers"]
            assert "X-Request-ID" in project_operation["responses"]["201"]["headers"]


def test_required_mode_request_ids_and_openapi_contract(tmp_path: Path) -> None:
    asyncio.run(_configuration_and_request_id_flow(tmp_path / "required-mode"))


async def _profile_and_job_header_flow(data_dir: Path) -> None:
    application = create_app(Settings(data_dir=data_dir), start_worker=False)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            profile_headers = {
                "Idempotency-Key": "novel-platform:profile-key-0001",
                "X-Request-ID": "request-profile-0001",
            }
            profile_body = {
                "name": "Reusable profile",
                "source_language": "en",
                "target_language": "fr",
                "provider_id": "mock",
            }
            profile = await client.post("/api/profiles", headers=profile_headers, json=profile_body)
            profile_replay = await client.post(
                "/api/profiles", headers=profile_headers, json=profile_body
            )
            assert profile.status_code == 201
            assert profile_replay.status_code == 200
            assert profile.json()["id"] == profile_replay.json()["id"]
            assert profile_replay.headers["Idempotency-Replayed"] == "true"
            assert (await client.get(profile.headers["Location"])).status_code == 200

            project = await client.post(
                "/api/projects",
                data={
                    "name": "Job headers",
                    "kind": "novel",
                    "source_language": "en",
                    "target_language": "fr",
                },
                files={"source": ("source.txt", b"Queued once.", "text/plain")},
            )
            project_id = project.json()["id"]
            job_headers = {
                "Idempotency-Key": "novel-platform:job-header-key-0001",
                "X-Request-ID": "request-job-first-0001",
            }
            job = await client.post(
                f"/api/projects/{project_id}/jobs", headers=job_headers, json={}
            )
            replay = await client.post(
                f"/api/projects/{project_id}/jobs", headers=job_headers, json={}
            )
            coalesced = await client.post(
                f"/api/projects/{project_id}/jobs",
                headers={"Idempotency-Key": "novel-platform:job-header-key-0002"},
                json={},
            )
            assert job.status_code == 202
            assert replay.status_code == coalesced.status_code == 200
            assert job.json()["id"] == replay.json()["id"] == coalesced.json()["id"]
            assert job.headers["X-Job-Coalesced"] == "false"
            assert replay.headers["Idempotency-Replayed"] == "true"
            assert coalesced.headers["Idempotency-Replayed"] == "false"
            assert coalesced.headers["X-Job-Coalesced"] == "true"
            assert (await client.get(job.headers["Location"])).status_code == 200

            with sqlite3.connect(data_dir / "database" / "linguaspindle.sqlite3") as connection:
                request_id = connection.execute(
                    "SELECT request_id FROM jobs WHERE id = ?", (job.json()["id"],)
                ).fetchone()[0]
            assert request_id == "request-job-first-0001"


def test_profile_and_job_idempotency_headers_and_request_persistence(tmp_path: Path) -> None:
    asyncio.run(_profile_and_job_header_flow(tmp_path / "profile-job-api"))


def test_default_compatibility_mode_and_natural_job_controls(tmp_path: Path) -> None:
    service = ApplicationService(Settings(data_dir=tmp_path / "compatibility"))
    try:
        assert service.settings.require_idempotency_key is False
        project = service.create_project(
            name="Natural controls",
            kind="novel",
            source_language="en",
            target_language="fr",
            source_name="source.txt",
            source_bytes=b"Controls.",
        )
        job = service.create_job(project_id=project["id"])
        first_pause = service.pause_job(job["id"])
        second_pause = service.pause_job(job["id"])
        assert first_pause["status"] == second_pause["status"] == "paused"
        first_resume = service.resume_job(job["id"])
        second_resume = service.resume_job(job["id"])
        assert first_resume["status"] == second_resume["status"] == "queued"
        first_cancel = service.cancel_job(job["id"])
        second_cancel = service.cancel_job(job["id"])
        assert first_cancel["status"] == second_cancel["status"] == "cancelled"
    finally:
        service.close()


def test_provider_key_is_absent_from_job_fingerprint_database_and_artifacts(
    tmp_path: Path,
) -> None:
    provider_key = "sk-provider-secret-must-not-persist-0001"
    settings = Settings(
        data_dir=tmp_path / "provider-fingerprint",
        openai_api_key=provider_key,
    )
    service = ApplicationService(settings)
    try:
        project = service.create_project(
            name="Secret-free fingerprint",
            kind="novel",
            source_language="en",
            target_language="fr",
            source_name="source.txt",
            source_bytes=b"No secret.",
        )
        job = service.create_job(project_id=project["id"], provider_id="openai-compatible")
        assert job["status"] == "queued"
        persisted = b"".join(
            path.read_bytes() for path in settings.data_dir.rglob("*") if path.is_file()
        )
        assert provider_key.encode() not in persisted
        with sqlite3.connect(settings.database_path) as connection:
            fingerprint = connection.execute(
                "SELECT execution_fingerprint FROM jobs WHERE id = ?", (job["id"],)
            ).fetchone()[0]
        assert fingerprint.startswith("job-execution.v1:")
        assert provider_key not in fingerprint
    finally:
        service.close()


def test_rebuild_and_retry_replay_do_not_repeat_side_effects(tmp_path: Path) -> None:
    # Rebuild is exercised through the same ASGI resource-replay protocol in the dedicated API
    # test below; retry uses the application boundary to assert one durable transition.
    service = ApplicationService(Settings(data_dir=tmp_path / "retry"))
    try:
        project = service.create_project(
            name="Retry once",
            kind="novel",
            source_language="en",
            target_language="fr",
            source_name="source.txt",
            source_bytes=b"[[MOCK_FAIL]]",
        )
        job = service.create_job(project_id=project["id"])
        assert JobRunner(service).run_once() is True
        assert service.get_job(job["id"])["status"] == "partially_succeeded"
        context = _context("novel-platform:retry-key-0001")
        first = service.retry_job_operation(job["id"], idempotency=context)
        replay = service.retry_job_operation(job["id"], idempotency=context)
        assert first.value["status"] == "queued"
        assert replay.value["id"] == job["id"]
        assert replay.replayed is True
        with sqlite3.connect(service.settings.database_path) as connection:
            retry_records = connection.execute(
                "SELECT COUNT(*) FROM idempotency_records WHERE scope LIKE '%:retry'"
            ).fetchone()[0]
        assert retry_records == 1
    finally:
        service.close()
