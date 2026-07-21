"""Restart-aware sequential Pipeline runner and built-in Step implementations."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..adapters.base import (
    AdapterHealth,
    MangaAdapterResult,
    MangaTranslationAdapter,
)
from ..application import ApplicationService
from ..core import (
    BatchStatus,
    MangaManifest,
    MangaPageTranslation,
    MangaTranslationResult,
    TranslationOptions,
    TranslationStatus,
    build_manga_output,
    extract_manga_pages,
    inspect_document,
    inspect_manga,
    rebuild_document,
    translate_manga,
    translate_segments,
)
from ..core.txt import decode_txt
from ..errors import ErrorCode, LinguaError
from ..models import Artifact, Job, Project, StepRun
from .state import JobStatus, StepStatus


class PauseRequested(Exception):
    pass


class CancelRequested(Exception):
    pass


@dataclass(frozen=True, slots=True)
class StepResult:
    output_artifact_ids: list[str]
    partial_error: LinguaError | None = None


class _CachedHealthMangaAdapter:
    """Keep the public per-call health contract without repeating remote probes per page."""

    def __init__(self, delegate: MangaTranslationAdapter):
        self._delegate = delegate
        self._health: AdapterHealth | None = None
        self.manifest = delegate.manifest

    def health(self) -> AdapterHealth:
        if self._health is None:
            self._health = self._delegate.health()
        return self._health

    def translate_image(
        self,
        *,
        image: bytes,
        filename: str,
        source_language: str,
        target_language: str,
    ) -> MangaAdapterResult:
        return self._delegate.translate_image(
            image=image,
            filename=filename,
            source_language=source_language,
            target_language=target_language,
        )


@dataclass(frozen=True, slots=True)
class ExecutionJob:
    id: str
    project_id: str
    project_kind: str
    project_name: str
    source_language: str
    target_language: str
    pipeline_key: str
    provider_id: str
    adapter_id: str | None
    profile: dict[str, Any]


class ExecutionContext:
    def __init__(
        self,
        service: ApplicationService,
        job: ExecutionJob,
        step: StepRun,
        input_artifacts: list[Artifact],
    ):
        self.service = service
        self.job = job
        self.step = step
        self.input_artifacts = input_artifacts

    def checkpoint(self) -> None:
        status, request = self.service.job_control(self.job.id)
        if request == "cancel" or status == JobStatus.CANCELLING:
            raise CancelRequested
        if request == "pause":
            raise PauseRequested

    def progress(self, value: float) -> None:
        self.service.set_progress(self.job.id, self.step.id, value)

    def log(self, level: str, message: str, details: dict[str, Any] | None = None) -> None:
        self.service.add_log(self.step.id, level, message, details)

    def payload(self, artifact: Artifact) -> bytes:
        return self.service.store.read_bytes(artifact.storage_key)

    def path(self, artifact: Artifact) -> Path:
        return self.service.store.path(artifact.storage_key)

    def create_artifact(
        self,
        *,
        kind: str,
        filename: str,
        media_type: str,
        payload: bytes,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        return self.service.create_artifact(
            project_id=self.job.project_id,
            job_id=self.job.id,
            step_run_id=self.step.id,
            kind=kind,
            filename=filename,
            media_type=media_type,
            payload=payload,
            metadata=metadata,
        )

    def create_artifact_from_path(
        self,
        *,
        kind: str,
        filename: str,
        media_type: str,
        source_path: Path,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        return self.service.create_artifact_from_path(
            project_id=self.job.project_id,
            job_id=self.job.id,
            step_run_id=self.step.id,
            kind=kind,
            filename=filename,
            media_type=media_type,
            source_path=source_path,
            metadata=metadata,
        )


StepHandler = Callable[[ExecutionContext], StepResult]


class JobRunner:
    """One durable local runner; queued Jobs are claimed through SQLite."""

    def __init__(self, service: ApplicationService):
        self.service = service
        self.runner_token = __import__("uuid").uuid4().hex
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._handlers: dict[str, StepHandler] = {
            "inspect_epub": self._inspect_epub,
            "segment_epub": self._segment_epub,
            "detect_encoding": self._detect_encoding,
            "extract_text": self._extract_text,
            "segment_text": self._segment_text,
            "translate_text": self._translate_text,
            "quality_check": self._quality_check,
            "export_novel": self._export_novel,
            "export_epub": self._export_epub,
            "prepare_manga": self._prepare_manga,
            "translate_manga": self._translate_manga,
            "export_manga": self._export_manga,
        }

    def start(self, *, recover: bool = True) -> None:
        if self._thread and self._thread.is_alive():
            return
        if recover:
            self.service.recover_interrupted_jobs()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="linguaspindle-job-runner", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except Exception:
                # A concurrent destructive filesystem/database event must not permanently
                # disable later queued Jobs. Per-Job failures are persisted by ``_execute``.
                worked = False
            if not worked:
                self._stop.wait(self.service.settings.worker_poll_seconds)

    def run_once(self) -> bool:
        job_id = self.service.claim_next_job(self.runner_token)
        if job_id is None:
            return False
        self._execute(job_id)
        return True

    def run_until_terminal(self, job_id: str, timeout: float = 300.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.service.get_job(job_id)
            if job["status"] in {
                JobStatus.CANCELLED,
                JobStatus.SUCCEEDED,
                JobStatus.FAILED,
                JobStatus.PARTIALLY_SUCCEEDED,
                JobStatus.PAUSED,
            }:
                return job
            if job["status"] == JobStatus.QUEUED:
                self.run_once()
            else:
                time.sleep(0.05)
        raise LinguaError(ErrorCode.TIMEOUT, "Timed out waiting for Job completion")

    def _execution_job(self, job_id: str) -> tuple[ExecutionJob, list[StepRun]]:
        with self.service.database.session() as session:
            job = session.scalar(
                select(Job)
                .where(Job.id == job_id)
                .options(selectinload(Job.steps), selectinload(Job.project))
            )
            if job is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Claimed Job no longer exists")
            project: Project = job.project
            record = ExecutionJob(
                id=job.id,
                project_id=job.project_id,
                project_kind=project.kind,
                project_name=project.name,
                source_language=project.source_language,
                target_language=project.target_language,
                pipeline_key=job.pipeline_key,
                provider_id=job.provider_id,
                adapter_id=job.adapter_id,
                profile=json.loads(job.profile_snapshot_json),
            )
            steps = list(job.steps)
            for step in steps:
                session.expunge(step)
            return record, steps

    def _execute(self, job_id: str) -> None:
        partial_error: LinguaError | None = None
        try:
            job, steps = self._execution_job(job_id)
            for step in steps:
                if step.status == StepStatus.SUCCEEDED:
                    continue
                status, request = self.service.job_control(job_id)
                if request == "pause":
                    self.service.pause_between_steps(job_id)
                    return
                if request == "cancel" or status == JobStatus.CANCELLING:
                    self.service.cancel_between_steps(job_id)
                    return
                inputs = self._input_artifacts(job, step, steps)
                self.service.step_inputs(step.id, [artifact.id for artifact in inputs])
                running_step = self.service.start_step(step.id)
                context = ExecutionContext(self.service, job, running_step, inputs)
                context.log(
                    "INFO",
                    "Step started",
                    {
                        "attempt": running_step.attempt_count,
                        "capability": running_step.capability,
                        "input_artifact_ids": [artifact.id for artifact in inputs],
                    },
                )
                try:
                    result = self._handlers[running_step.step_key](context)
                    if result.partial_error:
                        self.service.finish_step(
                            running_step.id,
                            status=StepStatus.PARTIALLY_SUCCEEDED,
                            output_artifact_ids=result.output_artifact_ids,
                            error=result.partial_error,
                        )
                        partial_error = result.partial_error
                        context.log(
                            "WARNING",
                            "Step partially succeeded",
                            {"error_code": result.partial_error.code},
                        )
                    else:
                        self.service.finish_step(
                            running_step.id,
                            status=StepStatus.SUCCEEDED,
                            output_artifact_ids=result.output_artifact_ids,
                        )
                        context.log(
                            "INFO",
                            "Step succeeded",
                            {"output_artifact_ids": result.output_artifact_ids},
                        )
                    self.service.set_progress(job_id, running_step.id, 1.0)
                except PauseRequested:
                    context.log("INFO", "Pause reached a safe boundary")
                    self.service.pause_running_job(job_id, running_step.id)
                    return
                except CancelRequested:
                    context.log("INFO", "Cancellation reached a safe boundary")
                    self.service.cancel_running_job(job_id, running_step.id)
                    return
                except LinguaError as exc:
                    context.log(
                        "ERROR",
                        exc.message,
                        {"error_code": exc.code, "details": exc.details or {}},
                    )
                    self.service.finish_step(running_step.id, status=StepStatus.FAILED, error=exc)
                    self.service.finish_job(job_id, status=JobStatus.FAILED, error=exc)
                    return
                except Exception as exc:
                    normalized = LinguaError(
                        ErrorCode.UNKNOWN,
                        "Unexpected Step failure",
                        {"exception_type": type(exc).__name__},
                    )
                    context.log(
                        "ERROR",
                        normalized.message,
                        {"error_code": normalized.code, "exception_type": type(exc).__name__},
                    )
                    self.service.finish_step(
                        running_step.id, status=StepStatus.FAILED, error=normalized
                    )
                    self.service.finish_job(job_id, status=JobStatus.FAILED, error=normalized)
                    return
            if partial_error:
                self.service.finish_job(
                    job_id, status=JobStatus.PARTIALLY_SUCCEEDED, error=partial_error
                )
            else:
                self.service.finish_job(job_id, status=JobStatus.SUCCEEDED)
        except LinguaError as exc:
            self._finish_active_job_if_present(job_id, exc)
        except Exception as exc:
            normalized = LinguaError(
                ErrorCode.UNKNOWN,
                "Unexpected Pipeline failure",
                {"exception_type": type(exc).__name__},
            )
            self._finish_active_job_if_present(job_id, normalized)

    def _finish_active_job_if_present(self, job_id: str, error: LinguaError) -> None:
        """Best-effort failure publication that tolerates a concurrently removed record."""

        try:
            current = self.service.get_job(job_id)
        except LinguaError as lookup_error:
            if lookup_error.code == ErrorCode.NOT_FOUND:
                return
            raise
        if current["status"] not in {JobStatus.RUNNING, JobStatus.CANCELLING}:
            return
        try:
            self.service.finish_job(job_id, status=JobStatus.FAILED, error=error)
        except LinguaError as finish_error:
            if finish_error.code != ErrorCode.NOT_FOUND:
                raise

    def _step_outputs(self, steps: list[StepRun], key: str) -> list[str]:
        step = next((candidate for candidate in steps if candidate.step_key == key), None)
        if step is None:
            return []
        with self.service.database.session() as session:
            fresh = session.get(StepRun, step.id)
            return json.loads(fresh.output_artifact_ids_json) if fresh else []

    def _input_artifacts(
        self, job: ExecutionJob, step: StepRun, steps: list[StepRun]
    ) -> list[Artifact]:
        source = self.service.source_artifact(job.project_id)
        ids: list[str]
        if step.step_key in {"detect_encoding", "inspect_epub", "prepare_manga"}:
            ids = [source.id]
        elif step.step_key == "segment_epub":
            ids = self._step_outputs(steps, "inspect_epub")
        elif step.step_key == "extract_text":
            ids = [source.id, *self._step_outputs(steps, "detect_encoding")]
        elif step.step_key == "segment_text":
            ids = self._step_outputs(steps, "extract_text")
        elif step.step_key == "translate_text":
            ids = [
                *self._step_outputs(steps, "segment_text"),
                *self._step_outputs(steps, "segment_epub"),
            ]
        elif step.step_key == "quality_check":
            ids = self._step_outputs(steps, "translate_text")
        elif step.step_key == "export_novel":
            ids = [
                *self._step_outputs(steps, "translate_text"),
                *self._step_outputs(steps, "quality_check"),
            ]
        elif step.step_key == "export_epub":
            ids = [
                *self._step_outputs(steps, "inspect_epub"),
                *self._step_outputs(steps, "translate_text"),
                *self._step_outputs(steps, "quality_check"),
            ]
        elif step.step_key == "translate_manga":
            ids = self._step_outputs(steps, "prepare_manga")
        elif step.step_key == "export_manga":
            ids = self._step_outputs(steps, "translate_manga")
        else:
            ids = []
        return self.service.artifact_rows(ids)

    def _core_options(self, job: ExecutionJob) -> TranslationOptions:
        profile = job.profile
        configured_retries = (
            self.service.settings.openai_max_retries
            if job.provider_id == "openai-compatible"
            else 0
        )
        configured_concurrency = (
            self.service.settings.openai_concurrency_limit
            if job.provider_id == "openai-compatible"
            else 1
        )
        return TranslationOptions(
            source_language=job.source_language,
            target_language=job.target_language,
            style=str(profile.get("style", "")),
            prompt_template=str(profile.get("prompt_template", "{text}")),
            prompt_version=str(profile.get("prompt_version", "v1")),
            model_parameters=cast(dict[str, Any], profile.get("model_parameters", {})),
            max_segment_chars=1_800,
            # The durable runner checkpoints one Segment at a time, while the
            # pure core uses this limit when a caller submits a batch directly.
            concurrency=configured_concurrency,
            max_retries=configured_retries,
            retry_backoff_seconds=0.25 if configured_retries else 0,
            max_source_bytes=self.service.settings.max_upload_bytes,
        )

    def _runtime_translation_input_hash(self, job: ExecutionJob, core_input_hash: str) -> str:
        """Bind reusable text to the effective Provider execution contract."""

        payload = {
            "schema_version": "runtime-translation-input.v1",
            "core_input_hash": core_input_hash,
            "provider_id": job.provider_id,
            "model": job.profile.get("model"),
            "context_strategy": job.profile.get("context_strategy"),
            "provider_endpoint": (
                self.service.settings.openai_base_url
                if job.provider_id == "openai-compatible"
                else None
            ),
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def _inspect_epub(self, context: ExecutionContext) -> StepResult:
        source = context.input_artifacts[0]
        manifest = inspect_document(
            context.path(source),
            filename=source.filename,
            options=self._core_options(context.job),
            archive_limits=self.service.settings.archive_limits(),
        )
        document_count = len({segment.source_document for segment in manifest.segments})
        artifact = context.create_artifact(
            kind="epub_package_manifest",
            filename="epub-package-manifest.json",
            media_type="application/json",
            payload=json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2).encode(),
            metadata={
                "source_artifact_id": source.id,
                "epub_version": manifest.metadata.get("epub_version"),
                "document_count": document_count,
                "text_unit_count": len(manifest.segments),
            },
        )
        context.log(
            "INFO",
            "EPUB package inspected",
            {
                "epub_version": manifest.metadata.get("epub_version"),
                "documents": document_count,
                "text_units": len(manifest.segments),
            },
        )
        return StepResult([artifact.id])

    def _segment_epub(self, context: ExecutionContext) -> StepResult:
        manifest_artifact = next(
            artifact
            for artifact in context.input_artifacts
            if artifact.kind == "epub_package_manifest"
        )
        source = self.service.source_artifact(context.job.project_id)
        public_manifest = inspect_document(
            context.path(source),
            filename=source.filename,
            options=self._core_options(context.job),
            archive_limits=self.service.settings.archive_limits(),
        )
        records = [
            {
                "segment_id": segment.segment_id,
                "sequence": segment.order,
                "source_text": segment.source_text,
                "source_artifact_id": source.id,
                "source_document": segment.source_document,
                "content_role": segment.content_role,
                "locator": segment.locator.to_epub_dict(),
                "source_text_hash": segment.source_hash,
                "translation_input_hash": self._runtime_translation_input_hash(
                    context.job, segment.translation_input_hash
                ),
            }
            for segment in public_manifest.segments
        ]
        reused = self.service.replace_segments(
            project_id=context.job.project_id,
            job_id=context.job.id,
            segments=records,
            profile=context.job.profile,
        )
        artifact = context.create_artifact(
            kind="epub_segments",
            filename="epub-segments.json",
            media_type="application/json",
            payload=json.dumps(
                {
                    "version": 1,
                    "source_artifact_id": source.id,
                    "manifest_artifact_id": manifest_artifact.id,
                    "segment_count": len(records),
                    "reused_segment_count": reused,
                    "public_manifest_schema": public_manifest.schema_version,
                    "segment_ids": [segment.segment_id for segment in public_manifest.segments],
                },
                ensure_ascii=False,
                indent=2,
            ).encode(),
            metadata={"segment_count": len(records), "reused_segment_count": reused},
        )
        context.log(
            "INFO",
            "EPUB visible text was segmented",
            {"segments": len(records), "reused_segments": reused},
        )
        return StepResult([artifact.id])

    def _detect_encoding(self, context: ExecutionContext) -> StepResult:
        source = context.input_artifacts[0]
        decoded = decode_txt(context.payload(source))
        artifact = context.create_artifact(
            kind="novel_encoding",
            filename="encoding.json",
            media_type="application/json",
            payload=json.dumps(
                {
                    "source_artifact_id": source.id,
                    "encoding": decoded.encoding,
                    "coherence": decoded.confidence,
                    "newline": decoded.newline,
                },
                ensure_ascii=False,
                indent=2,
            ).encode(),
            metadata={"encoding": decoded.encoding, "newline": decoded.newline},
        )
        context.log("INFO", "Source encoding detected", {"encoding": decoded.encoding})
        return StepResult([artifact.id])

    def _extract_text(self, context: ExecutionContext) -> StepResult:
        source = next(
            artifact for artifact in context.input_artifacts if artifact.kind == "source_original"
        )
        decoded = decode_txt(context.payload(source))
        artifact = context.create_artifact(
            kind="novel_text_extracted",
            filename="source-normalized.txt",
            media_type="text/plain; charset=utf-8",
            payload=decoded.text.encode(),
            metadata={"source_artifact_id": source.id, "encoding": decoded.encoding},
        )
        return StepResult([artifact.id])

    @staticmethod
    def segment_text(text: str, maximum_chars: int = 1_800) -> list[str]:
        manifest = inspect_document(
            text.encode(),
            filename="source.txt",
            options=TranslationOptions(max_segment_chars=maximum_chars),
        )
        return [segment.source_text for segment in manifest.segments]

    def _segment_text(self, context: ExecutionContext) -> StepResult:
        source = self.service.source_artifact(context.job.project_id)
        manifest = inspect_document(
            context.path(source),
            filename=source.filename,
            options=self._core_options(context.job),
        )
        records = [
            {
                "segment_id": segment.segment_id,
                "sequence": segment.order,
                "source_text": segment.source_text,
                "source_artifact_id": source.id,
                "source_document": segment.source_document,
                "content_role": segment.content_role,
                "locator": segment.locator.to_dict(),
                "source_text_hash": segment.source_hash,
                "translation_input_hash": self._runtime_translation_input_hash(
                    context.job, segment.translation_input_hash
                ),
            }
            for segment in manifest.segments
        ]
        self.service.replace_segments(
            project_id=context.job.project_id,
            job_id=context.job.id,
            segments=records,
            profile=context.job.profile,
        )
        artifact = context.create_artifact(
            kind="novel_segments",
            filename="segments.json",
            media_type="application/json",
            payload=json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2).encode(),
            metadata={"segment_count": len(manifest.segments)},
        )
        context.log("INFO", "TXT was segmented", {"segments": len(manifest.segments)})
        return StepResult([artifact.id])

    def _translate_text(self, context: ExecutionContext) -> StepResult:
        provider = self.service.providers.get(context.job.provider_id)
        profile = context.job.profile
        rows = self.service.segment_rows(context.job.id)
        source = self.service.source_artifact(context.job.project_id)
        public_manifest = inspect_document(
            context.path(source),
            filename=source.filename,
            options=self._core_options(context.job),
            archive_limits=self.service.settings.archive_limits(),
        )
        by_id = {segment.segment_id: segment for segment in public_manifest.segments}
        by_order = {segment.order: segment for segment in public_manifest.segments}
        failures: list[LinguaError] = []
        reused_count = sum(1 for row in rows if row.status == "succeeded")
        if reused_count:
            context.log(
                "INFO",
                "Previously successful translations were reused",
                {"reused_segments": reused_count},
            )
        current_document: str | None = None
        for index, segment in enumerate(rows):
            if segment.status == "succeeded":
                continue
            context.checkpoint()
            if segment.source_document and segment.source_document != current_document:
                current_document = segment.source_document
                context.log(
                    "INFO",
                    "Processing EPUB document",
                    {"document": current_document},
                )
            self.service.update_segment(segment.id, status="running")
            public_segment = by_id.get(segment.segment_key or "") or by_order.get(segment.sequence)
            if public_segment is None:
                raise LinguaError(
                    ErrorCode.SOURCE_MISMATCH,
                    "Persisted Segment no longer matches the immutable source",
                    {"sequence": segment.sequence},
                )
            result = translate_segments(
                (public_segment,),
                provider,
                self._core_options(context.job),
                sensitive_values=(self.service.settings.openai_api_key or "",),
            ).records[0]
            if result.status is TranslationStatus.SUCCEEDED and result.translated_text is not None:
                self.service.update_segment(
                    segment.id,
                    status="succeeded",
                    translated_text=result.translated_text,
                    model=result.model,
                )
                if result.usage is not None:
                    context.log(
                        "INFO",
                        "Provider usage reported",
                        {"sequence": segment.sequence, "usage": result.usage},
                    )
            else:
                error = result.error
                exc = LinguaError(
                    error.code if error else ErrorCode.UNKNOWN,
                    error.message if error else "Segment translation failed",
                    cast(dict[str, Any], error.details) if error else None,
                    error.retryable if error else False,
                )
                self.service.update_segment(segment.id, status="failed", error=exc)
                context.log(
                    "ERROR",
                    "Segment translation failed",
                    {"sequence": segment.sequence, "error_code": exc.code},
                )
                failures.append(exc)
            context.progress((index + 1) / max(len(rows), 1))
            context.checkpoint()
        public_segments = self.service.list_segments(context.job.project_id, job_id=context.job.id)
        if context.job.pipeline_key == "novel_epub_v1":
            translation_payload: dict[str, Any] = {
                "version": 1,
                "provider_id": context.job.provider_id,
                "segment_count": len(public_segments),
                "succeeded_count": sum(
                    1 for segment in public_segments if segment["status"] == "succeeded"
                ),
                "failed_count": len(failures),
                "reused_count": reused_count,
                "segment_ids": [segment["segment_id"] for segment in public_segments],
            }
            artifact_kind = "epub_translations"
            artifact_filename = "epub-translations.json"
        else:
            translation_payload = {
                "version": 1,
                "provider_id": context.job.provider_id,
                "profile": profile,
                "segments": public_segments,
            }
            artifact_kind = "novel_translations"
            artifact_filename = "translations.json"
        artifact = context.create_artifact(
            kind=artifact_kind,
            filename=artifact_filename,
            media_type="application/json",
            payload=json.dumps(translation_payload, ensure_ascii=False, indent=2).encode(),
            metadata={
                "segment_count": len(public_segments),
                "failed_count": len(failures),
                "reused_count": reused_count,
            },
        )
        partial = None
        if failures:
            partial = LinguaError(
                failures[0].code,
                f"{len(failures)} of {len(rows)} segments failed translation",
                {"failed_segments": len(failures), "total_segments": len(rows)},
                retryable=True,
            )
        return StepResult([artifact.id], partial_error=partial)

    def _quality_check(self, context: ExecutionContext) -> StepResult:
        segments = self.service.segment_rows(context.job.id)
        findings: list[dict[str, str]] = []
        for segment in segments:
            if segment.status != "succeeded" or not segment.translated_text:
                findings.append(
                    {
                        "segment_id": segment.id,
                        "category": "missing_translation",
                        "severity": "error",
                        "message": "Segment has no successful translation.",
                    }
                )
                continue
            if segment.translated_text.strip() == segment.source_text.strip():
                findings.append(
                    {
                        "segment_id": segment.id,
                        "category": "unchanged_text",
                        "severity": "warning",
                        "message": "Translation is identical to the source text.",
                    }
                )
            ratio = len(segment.translated_text) / max(len(segment.source_text), 1)
            if ratio < 0.25 or ratio > 4.0:
                findings.append(
                    {
                        "segment_id": segment.id,
                        "category": "length_ratio",
                        "severity": "warning",
                        "message": f"Translation/source length ratio is {ratio:.2f}.",
                    }
                )
        self.service.replace_qa(context.job.id, context.job.project_id, findings)
        artifact = context.create_artifact(
            kind="qa_report",
            filename="qa-report.json",
            media_type="application/json",
            payload=json.dumps(
                {"version": 1, "findings": findings}, ensure_ascii=False, indent=2
            ).encode(),
            metadata={"finding_count": len(findings)},
        )
        return StepResult([artifact.id])

    def _export_novel(self, context: ExecutionContext) -> StepResult:
        segments = self.service.list_segments(context.job.project_id, job_id=context.job.id)
        if not segments:
            raise LinguaError(ErrorCode.OUTPUT_MISSING, "No translation segments to export")
        source = self.service.source_artifact(context.job.project_id)
        manifest = inspect_document(
            context.path(source),
            filename=source.filename,
            options=self._core_options(context.job),
            archive_limits=self.service.settings.archive_limits(),
        )
        translations = {
            str(segment["segment_id"]): str(segment["translated_text"])
            for segment in segments
            if segment["translated_text"] is not None
            and segment["status"] == TranslationStatus.SUCCEEDED.value
        }
        output = io.BytesIO()
        build = rebuild_document(
            context.path(source),
            manifest,
            translations,
            output,
            target_language=context.job.target_language,
            archive_limits=self.service.settings.archive_limits(),
        )
        txt_artifact = context.create_artifact(
            kind="novel_export_txt",
            filename=f"{context.job.project_name}-translated.txt",
            media_type="text/plain; charset=utf-8",
            payload=output.getvalue(),
            metadata={
                "format": "txt",
                "segments": len(segments),
                "translated_segments": build.translated_count,
                "preserved_segments": build.preserved_count,
                "source_artifact_id": source.id,
            },
        )
        structured = {
            "schema_version": 1,
            "project": {
                "id": context.job.project_id,
                "name": context.job.project_name,
                "source_language": context.job.source_language,
                "target_language": context.job.target_language,
            },
            "job_id": context.job.id,
            "profile": context.job.profile,
            "manifest": manifest.to_dict(),
            "segments": segments,
            "build": build.to_dict(),
        }
        json_artifact = context.create_artifact(
            kind="novel_export_json",
            filename=f"{context.job.project_name}-translated.json",
            media_type="application/json",
            payload=json.dumps(structured, ensure_ascii=False, indent=2).encode(),
            metadata={"format": "json", "schema_version": 1},
        )
        return StepResult([txt_artifact.id, json_artifact.id])

    def _export_epub(self, context: ExecutionContext) -> StepResult:
        manifest_artifact = next(
            artifact
            for artifact in context.input_artifacts
            if artifact.kind == "epub_package_manifest"
        )
        source = self.service.source_artifact(context.job.project_id)
        segments = self.service.list_segments(context.job.project_id, job_id=context.job.id)
        if not segments:
            raise LinguaError(ErrorCode.OUTPUT_MISSING, "No EPUB translation segments to export")
        manifest = inspect_document(
            context.path(source),
            filename=source.filename,
            options=self._core_options(context.job),
            archive_limits=self.service.settings.archive_limits(),
        )
        translations = {
            str(segment["segment_id"]): str(segment["translated_text"])
            for segment in segments
            if segment["translated_text"] is not None
            and segment["status"] == TranslationStatus.SUCCEEDED.value
        }
        failed_count = sum(1 for segment in segments if segment["status"] != "succeeded")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.service.settings.cache_dir,
                prefix="epub-export-",
                suffix=".epub",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
            build = rebuild_document(
                context.path(source),
                manifest=manifest,
                translations=translations,
                output=temporary_path,
                target_language=context.job.target_language,
                overwrite=True,
                archive_limits=self.service.settings.archive_limits(),
            )
            epub_artifact = context.create_artifact_from_path(
                kind="novel_export_epub",
                filename=f"{context.job.project_name}-translated.epub",
                media_type="application/epub+zip",
                source_path=temporary_path,
                metadata={
                    "format": "epub",
                    "source_artifact_id": source.id,
                    "source_epub_artifact_id": source.id,
                    "manifest_artifact_id": manifest_artifact.id,
                    "project_id": context.job.project_id,
                    "job_id": context.job.id,
                    "target_language": context.job.target_language,
                    "segment_count": len(segments),
                    "fallback_segment_count": failed_count,
                },
            )
            validation = dict(build.details)
            validation["build"] = build.to_dict()
            validation_artifact = context.create_artifact(
                kind="epub_validation_report",
                filename="epub-validation-report.json",
                media_type="application/json",
                payload=json.dumps(validation, ensure_ascii=False, indent=2).encode(),
                metadata={
                    "epub_artifact_id": epub_artifact.id,
                    "valid": bool(validation.get("valid", True)),
                },
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        context.log(
            "INFO",
            "Translated EPUB rebuilt and independently validated",
            {
                "epub_artifact_id": epub_artifact.id,
                "validation_artifact_id": validation_artifact.id,
                "fallback_segments": failed_count,
            },
        )
        return StepResult([epub_artifact.id, validation_artifact.id])

    def _prepare_manga(self, context: ExecutionContext) -> StepResult:
        source = context.input_artifacts[0]
        manifest = inspect_manga(
            context.path(source),
            filename=source.filename,
            archive_limits=self.service.settings.archive_limits(),
            maximum_bytes=self.service.settings.max_upload_bytes,
        )
        page_ids: list[str] = []
        manifest_pages: list[dict[str, Any]] = []
        extracted = extract_manga_pages(
            context.path(source),
            manifest,
            archive_limits=self.service.settings.archive_limits(),
            maximum_bytes=self.service.settings.max_upload_bytes,
        )
        for index, (page_record, payload) in enumerate(extracted, start=1):
            context.checkpoint()
            page = context.create_artifact(
                kind="manga_page_source",
                filename=f"{index:04d}-{page_record.name}",
                media_type=page_record.media_type,
                payload=payload,
                metadata={
                    "source_artifact_id": source.id,
                    "page": index,
                    "page_id": page_record.page_id,
                    "page_order": page_record.order,
                    "page_name": page_record.name,
                    "archive_member": page_record.archive_member,
                    "source_sha256": page_record.source_sha256,
                },
            )
            page_ids.append(page.id)
            manifest_pages.append(
                {
                    "page": index,
                    "page_id": page_record.page_id,
                    "artifact_id": page.id,
                    "name": page_record.name,
                }
            )
            context.progress(index / max(len(extracted), 1))
        manifest_artifact = context.create_artifact(
            kind="manga_manifest",
            filename="manga-manifest.json",
            media_type="application/json",
            payload=json.dumps(
                {
                    "schema_version": "runtime-manga-manifest.v1",
                    "version": 1,
                    "source_artifact_id": source.id,
                    "manifest": manifest.to_dict(),
                    "pages": manifest_pages,
                },
                ensure_ascii=False,
                indent=2,
            ).encode(),
            metadata={"page_count": len(page_ids)},
        )
        return StepResult([manifest_artifact.id, *page_ids])

    def _translate_manga(self, context: ExecutionContext) -> StepResult:
        if not context.job.adapter_id:
            raise LinguaError(ErrorCode.CONFIGURATION, "Manga Job has no configured Adapter")
        adapter = _CachedHealthMangaAdapter(
            self.service.adapters.get(context.job.adapter_id, "manga_full_pipeline")
        )
        manifest_artifact = next(
            artifact for artifact in context.input_artifacts if artifact.kind == "manga_manifest"
        )
        manifest_payload = json.loads(context.payload(manifest_artifact))
        raw_manifest = manifest_payload.get("manifest")
        if not isinstance(raw_manifest, dict):
            raise LinguaError(ErrorCode.INVALID_FORMAT, "Runtime Manga manifest is invalid")
        manifest = MangaManifest.from_dict(raw_manifest)
        artifact_map = {
            str(item["page_id"]): str(item["artifact_id"])
            for item in manifest_payload.get("pages", [])
            if isinstance(item, dict) and "page_id" in item and "artifact_id" in item
        }
        page_artifacts = {artifact.id: artifact for artifact in context.input_artifacts}
        prior_public = self.service.list_artifacts(
            project_id=context.job.project_id,
            job_id=context.job.id,
        )
        prior_translated_ids: dict[str, str] = {}
        for artifact in prior_public:
            if artifact["kind"] != "manga_page_translated":
                continue
            metadata = artifact.get("metadata", {})
            if isinstance(metadata, dict) and metadata.get("page_id"):
                prior_translated_ids[str(metadata["page_id"])] = str(artifact["id"])
        prior_translated = {
            artifact.id: artifact
            for artifact in self.service.artifact_rows(list(prior_translated_ids.values()))
        }
        outputs: list[str] = []
        page_results: list[MangaPageTranslation] = []
        reused_pages = 0
        for index, page in enumerate(manifest.pages, start=1):
            context.checkpoint()
            artifact_id = artifact_map.get(page.page_id)
            source_page = page_artifacts.get(artifact_id or "")
            if source_page is None:
                raise LinguaError(
                    ErrorCode.OUTPUT_MISSING,
                    "Runtime Manga page Artifact is missing",
                    {"page_id": page.page_id},
                )
            prior_id = prior_translated_ids.get(page.page_id)
            prior_artifact = prior_translated.get(prior_id or "")
            if prior_artifact is not None:
                prior_metadata = json.loads(prior_artifact.metadata_json)
                if prior_metadata.get("source_page_artifact_id") == source_page.id:
                    mapped = MangaPageTranslation(
                        page_id=page.page_id,
                        order=page.order,
                        name=page.name,
                        status=TranslationStatus.SUCCEEDED,
                        media_type=prior_artifact.media_type,
                        image=context.payload(prior_artifact),
                        attempts=0,
                        raw_result={"reused_artifact_id": prior_artifact.id},
                        logs=("successful page reused from the same Job",),
                    )
                    page_results.append(mapped)
                    outputs.append(prior_artifact.id)
                    reused_pages += 1
                    context.progress(index / max(len(manifest.pages), 1))
                    continue
            core_result = translate_manga(
                context.payload(source_page),
                adapter,
                self._core_options(context.job),
                filename=page.name,
                archive_limits=self.service.settings.archive_limits(),
                sensitive_values=(self.service.settings.openai_api_key or "",),
            )
            translated = core_result.pages[0]
            mapped = MangaPageTranslation(
                page_id=page.page_id,
                order=page.order,
                name=page.name,
                status=translated.status,
                media_type=translated.media_type,
                image=translated.image,
                attempts=translated.attempts,
                raw_result=translated.raw_result,
                logs=translated.logs,
                error=translated.error,
            )
            page_results.append(mapped)
            if mapped.status is TranslationStatus.SUCCEEDED and mapped.image is not None:
                image_artifact = context.create_artifact(
                    kind="manga_page_translated",
                    filename=f"translated-{page.name}",
                    media_type=mapped.media_type or page.media_type,
                    payload=mapped.image,
                    metadata={
                        "source_page_artifact_id": source_page.id,
                        "adapter_id": adapter.manifest.id,
                        "page": index,
                        "page_id": page.page_id,
                        "page_order": page.order,
                    },
                )
                outputs.append(image_artifact.id)
            raw_artifact = context.create_artifact(
                kind="adapter_raw_output",
                filename=(
                    f"adapter-{index:04d}.json"
                    if mapped.error is None
                    else f"adapter-{index:04d}-error.json"
                ),
                media_type="application/json",
                payload=json.dumps(
                    mapped.to_dict(include_binary=False), ensure_ascii=False, indent=2
                ).encode(),
                metadata={
                    "adapter_id": adapter.manifest.id,
                    "page": index,
                    "page_id": page.page_id,
                    "failed": mapped.error is not None,
                },
            )
            outputs.append(raw_artifact.id)
            if mapped.error is not None:
                context.log(
                    "ERROR",
                    "Manga page Adapter invocation failed",
                    {"page": index, "error_code": mapped.error.code},
                )
            context.progress(index / max(len(manifest.pages), 1))
            context.checkpoint()
        if reused_pages:
            context.log(
                "INFO",
                "Previously successful Manga pages were reused",
                {"reused_pages": reused_pages},
            )
        translated_count = sum(
            1 for page in page_results if page.status is TranslationStatus.SUCCEEDED
        )
        if translated_count == len(page_results):
            status = BatchStatus.SUCCEEDED
        elif translated_count:
            status = BatchStatus.PARTIALLY_SUCCEEDED
        else:
            status = BatchStatus.FAILED
        aggregate = MangaTranslationResult(
            manifest=manifest,
            pages=tuple(page_results),
            status=status,
            adapter_id=adapter.manifest.id,
        )
        aggregate_artifact = context.create_artifact(
            kind="manga_translation_result",
            filename="manga-translation-result.json",
            media_type="application/json",
            payload=json.dumps(
                aggregate.to_dict(include_binary=False), ensure_ascii=False, indent=2
            ).encode(),
            metadata={
                "adapter_id": adapter.manifest.id,
                "page_count": len(page_results),
                "translated_count": translated_count,
            },
        )
        outputs.append(aggregate_artifact.id)
        failures = [page.error for page in page_results if page.error is not None]
        partial = None
        if failures:
            partial = LinguaError(
                failures[0].code,
                f"{len(failures)} of {len(page_results)} manga pages failed",
                {"failed_pages": len(failures), "total_pages": len(page_results)},
                retryable=any(error.retryable for error in failures),
            )
        return StepResult(outputs, partial_error=partial)

    def _export_manga(self, context: ExecutionContext) -> StepResult:
        aggregate_artifact = next(
            (
                artifact
                for artifact in context.input_artifacts
                if artifact.kind == "manga_translation_result"
            ),
            None,
        )
        if aggregate_artifact is None:
            raise LinguaError(ErrorCode.OUTPUT_MISSING, "Manga translation result is missing")
        aggregate = MangaTranslationResult.from_dict(
            json.loads(context.payload(aggregate_artifact))
        )
        translated_artifacts = [
            artifact
            for artifact in context.input_artifacts
            if artifact.kind == "manga_page_translated"
        ]
        translated_by_id = {
            str(json.loads(artifact.metadata_json).get("page_id")): artifact
            for artifact in translated_artifacts
        }
        pages: list[MangaPageTranslation] = []
        for page in aggregate.pages:
            artifact = translated_by_id.get(page.page_id)
            pages.append(
                MangaPageTranslation(
                    page_id=page.page_id,
                    order=page.order,
                    name=page.name,
                    status=page.status,
                    media_type=page.media_type,
                    image=context.payload(artifact) if artifact is not None else None,
                    attempts=page.attempts,
                    raw_result=page.raw_result,
                    logs=page.logs,
                    error=page.error,
                )
            )
        result = MangaTranslationResult(
            manifest=aggregate.manifest,
            pages=tuple(pages),
            status=aggregate.status,
            adapter_id=aggregate.adapter_id,
        )
        buffer = io.BytesIO()
        build = build_manga_output(result, buffer)
        is_cbz = aggregate.manifest.source_format.value == "cbz"
        output_media_type = next(
            (
                page.media_type
                for page in pages
                if page.status is TranslationStatus.SUCCEEDED and page.media_type
            ),
            "application/octet-stream",
        )
        output_suffix = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
        }.get(output_media_type, ".bin")
        artifact = context.create_artifact(
            kind="manga_export_cbz" if is_cbz else "manga_export_image",
            filename=(
                f"{context.job.project_name}-translated.cbz"
                if is_cbz
                else f"{context.job.project_name}-translated{output_suffix}"
            ),
            media_type=("application/vnd.comicbook+zip" if is_cbz else output_media_type),
            payload=buffer.getvalue(),
            metadata={
                "format": "cbz" if is_cbz else "image",
                "page_count": build.translated_count,
                "preserved_page_count": build.preserved_count,
                "build": build.to_dict(),
            },
        )
        return StepResult([artifact.id])
