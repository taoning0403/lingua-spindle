"""Restart-aware sequential Pipeline runner and v0.1.0 Step implementations."""

from __future__ import annotations

import io
import json
import re
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from charset_normalizer import from_bytes
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..application import ApplicationService
from ..errors import ErrorCode, LinguaError
from ..models import Artifact, Job, Project, StepRun
from ..providers import TranslationRequest
from .state import JobStatus, StepStatus


class PauseRequested(Exception):
    pass


class CancelRequested(Exception):
    pass


@dataclass(frozen=True, slots=True)
class StepResult:
    output_artifact_ids: list[str]
    partial_error: LinguaError | None = None


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


StepHandler = Callable[[ExecutionContext], StepResult]


class JobRunner:
    """One durable local runner; queued Jobs are claimed through SQLite."""

    def __init__(self, service: ApplicationService):
        self.service = service
        self.runner_token = __import__("uuid").uuid4().hex
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._handlers: dict[str, StepHandler] = {
            "detect_encoding": self._detect_encoding,
            "extract_text": self._extract_text,
            "segment_text": self._segment_text,
            "translate_text": self._translate_text,
            "quality_check": self._quality_check,
            "export_novel": self._export_novel,
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
            worked = self.run_once()
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
            current = self.service.get_job(job_id)
            if current["status"] in {JobStatus.RUNNING, JobStatus.CANCELLING}:
                self.service.finish_job(job_id, status=JobStatus.FAILED, error=exc)
        except Exception as exc:
            normalized = LinguaError(
                ErrorCode.UNKNOWN,
                "Unexpected Pipeline failure",
                {"exception_type": type(exc).__name__},
            )
            current = self.service.get_job(job_id)
            if current["status"] in {JobStatus.RUNNING, JobStatus.CANCELLING}:
                self.service.finish_job(job_id, status=JobStatus.FAILED, error=normalized)

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
        if step.step_key in {"detect_encoding", "prepare_manga"}:
            ids = [source.id]
        elif step.step_key == "extract_text":
            ids = [source.id, *self._step_outputs(steps, "detect_encoding")]
        elif step.step_key == "segment_text":
            ids = self._step_outputs(steps, "extract_text")
        elif step.step_key == "translate_text":
            ids = self._step_outputs(steps, "segment_text")
        elif step.step_key == "quality_check":
            ids = self._step_outputs(steps, "translate_text")
        elif step.step_key == "export_novel":
            ids = [
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

    def _detect_encoding(self, context: ExecutionContext) -> StepResult:
        source = context.input_artifacts[0]
        payload = context.payload(source)
        match = from_bytes(payload).best()
        encoding = match.encoding if match and match.encoding else "utf_8"
        coherence = float(match.percent_coherence / 100) if match else 0.0
        artifact = context.create_artifact(
            kind="novel_encoding",
            filename="encoding.json",
            media_type="application/json",
            payload=json.dumps(
                {
                    "source_artifact_id": source.id,
                    "encoding": encoding,
                    "coherence": coherence,
                },
                ensure_ascii=False,
                indent=2,
            ).encode(),
            metadata={"encoding": encoding},
        )
        context.log("INFO", "Source encoding detected", {"encoding": encoding})
        return StepResult([artifact.id])

    def _extract_text(self, context: ExecutionContext) -> StepResult:
        source = next(
            artifact for artifact in context.input_artifacts if artifact.kind == "source_original"
        )
        encoding_artifact = next(
            artifact for artifact in context.input_artifacts if artifact.kind == "novel_encoding"
        )
        encoding = json.loads(context.payload(encoding_artifact))["encoding"]
        try:
            text = context.payload(source).decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError) as exc:
            raise LinguaError(
                ErrorCode.INVALID_FORMAT,
                "TXT source could not be decoded with the detected encoding",
                {"encoding": encoding},
            ) from exc
        normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.strip():
            raise LinguaError(ErrorCode.INVALID_FORMAT, "TXT source contains no text")
        artifact = context.create_artifact(
            kind="novel_text_extracted",
            filename="source-normalized.txt",
            media_type="text/plain; charset=utf-8",
            payload=normalized.encode(),
            metadata={"source_artifact_id": source.id, "encoding": encoding},
        )
        return StepResult([artifact.id])

    @staticmethod
    def segment_text(text: str, maximum_chars: int = 1_800) -> list[str]:
        paragraphs = [part.strip() for part in re.split(r"\n[ \t]*\n+", text) if part.strip()]
        segments: list[str] = []
        for paragraph in paragraphs:
            if len(paragraph) <= maximum_chars:
                segments.append(paragraph)
                continue
            sentences = [
                part.strip() for part in re.split(r"(?<=[。！？.!?])\s+", paragraph) if part.strip()
            ]
            current = ""
            for sentence in sentences:
                if len(sentence) > maximum_chars:
                    if current:
                        segments.append(current)
                        current = ""
                    words = sentence.split()
                    if len(words) == 1:
                        segments.extend(
                            sentence[index : index + maximum_chars]
                            for index in range(0, len(sentence), maximum_chars)
                        )
                        continue
                    for word in words:
                        candidate = f"{current} {word}".strip()
                        if len(candidate) > maximum_chars and current:
                            segments.append(current)
                            current = word
                        else:
                            current = candidate
                    continue
                candidate = f"{current} {sentence}".strip()
                if len(candidate) > maximum_chars and current:
                    segments.append(current)
                    current = sentence
                else:
                    current = candidate
            if current:
                segments.append(current)
        return segments

    def _segment_text(self, context: ExecutionContext) -> StepResult:
        source = next(
            artifact
            for artifact in context.input_artifacts
            if artifact.kind == "novel_text_extracted"
        )
        text = context.payload(source).decode("utf-8")
        segments = self.segment_text(text)
        if not segments:
            raise LinguaError(ErrorCode.INVALID_FORMAT, "No translatable TXT segments were found")
        self.service.replace_segments(
            project_id=context.job.project_id,
            job_id=context.job.id,
            texts=segments,
            profile=context.job.profile,
        )
        artifact = context.create_artifact(
            kind="novel_segments",
            filename="segments.json",
            media_type="application/json",
            payload=json.dumps(
                {
                    "version": 1,
                    "source_artifact_id": source.id,
                    "segments": [
                        {"sequence": index, "source_text": segment}
                        for index, segment in enumerate(segments)
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ).encode(),
            metadata={"segment_count": len(segments)},
        )
        context.log("INFO", "TXT was segmented", {"segments": len(segments)})
        return StepResult([artifact.id])

    def _translate_text(self, context: ExecutionContext) -> StepResult:
        provider = self.service.providers.get(context.job.provider_id)
        profile = context.job.profile
        rows = self.service.segment_rows(context.job.id)
        failures: list[LinguaError] = []
        for index, segment in enumerate(rows):
            if segment.status == "succeeded":
                continue
            context.checkpoint()
            self.service.update_segment(segment.id, status="running")
            request = TranslationRequest(
                text=segment.source_text,
                source_language=context.job.source_language,
                target_language=context.job.target_language,
                style=str(profile.get("style", "")),
                prompt_template=str(profile["prompt_template"]),
                prompt_version=str(profile.get("prompt_version", "v1")),
                model_parameters=dict(profile.get("model_parameters", {})),
            )
            try:
                result = provider.translate(request)
                self.service.update_segment(
                    segment.id,
                    status="succeeded",
                    translated_text=result.text,
                    model=result.model,
                )
                if result.usage is not None:
                    context.log(
                        "INFO",
                        "Provider usage reported",
                        {"sequence": segment.sequence, "usage": result.usage},
                    )
            except LinguaError as exc:
                self.service.update_segment(segment.id, status="failed", error=exc)
                context.log(
                    "ERROR",
                    "Segment translation failed",
                    {"sequence": segment.sequence, "error_code": exc.code},
                )
                failures.append(exc)
            context.progress((index + 1) / max(len(rows), 1))
        public_segments = self.service.list_segments(context.job.project_id, job_id=context.job.id)
        artifact = context.create_artifact(
            kind="novel_translations",
            filename="translations.json",
            media_type="application/json",
            payload=json.dumps(
                {
                    "version": 1,
                    "provider_id": context.job.provider_id,
                    "profile": profile,
                    "segments": public_segments,
                },
                ensure_ascii=False,
                indent=2,
            ).encode(),
            metadata={
                "segment_count": len(public_segments),
                "failed_count": len(failures),
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
        text_parts = []
        for segment in segments:
            if segment["translated_text"]:
                text_parts.append(segment["translated_text"])
            else:
                text_parts.append(
                    f"[Translation failed: {segment['error']['code']}]\n{segment['source_text']}"
                )
        txt_artifact = context.create_artifact(
            kind="novel_export_txt",
            filename=f"{context.job.project_name}-translated.txt",
            media_type="text/plain; charset=utf-8",
            payload=("\n\n".join(text_parts) + "\n").encode(),
            metadata={"format": "txt", "segments": len(segments)},
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
            "segments": segments,
        }
        json_artifact = context.create_artifact(
            kind="novel_export_json",
            filename=f"{context.job.project_name}-translated.json",
            media_type="application/json",
            payload=json.dumps(structured, ensure_ascii=False, indent=2).encode(),
            metadata={"format": "json", "schema_version": 1},
        )
        return StepResult([txt_artifact.id, json_artifact.id])

    def _prepare_manga(self, context: ExecutionContext) -> StepResult:
        source = context.input_artifacts[0]
        payload = context.payload(source)
        suffix = Path(source.filename).suffix.lower()
        page_ids: list[str] = []
        manifest_pages: list[dict[str, Any]] = []
        if suffix in _IMAGE_SUFFIXES:
            page = context.create_artifact(
                kind="manga_page_source",
                filename=source.filename,
                media_type=source.media_type,
                payload=payload,
                metadata={"source_artifact_id": source.id, "page": 1},
            )
            page_ids.append(page.id)
            manifest_pages.append({"page": 1, "artifact_id": page.id, "name": page.filename})
        else:
            try:
                archive = zipfile.ZipFile(io.BytesIO(payload))
            except zipfile.BadZipFile as exc:
                raise LinguaError(
                    ErrorCode.INVALID_FORMAT, "Manga archive is not a valid CBZ"
                ) from exc
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) > self.service.settings.max_archive_files:
                raise LinguaError(ErrorCode.INVALID_FORMAT, "Manga archive contains too many files")
            total = sum(item.file_size for item in members)
            if total > self.service.settings.max_archive_uncompressed_bytes:
                raise LinguaError(
                    ErrorCode.INVALID_FORMAT, "Manga archive expands beyond the configured limit"
                )
            image_members = []
            for member in members:
                safe_member = self.service.validate_archive_member(member.filename)
                if safe_member.suffix.lower() in _IMAGE_SUFFIXES:
                    image_members.append((member, safe_member))
            if not image_members:
                raise LinguaError(ErrorCode.INVALID_FORMAT, "Manga archive contains no images")
            image_members.sort(key=lambda item: str(item[1]).casefold())
            for index, (member, safe_member) in enumerate(image_members, start=1):
                context.checkpoint()
                image = archive.read(member)
                page = context.create_artifact(
                    kind="manga_page_source",
                    filename=f"{index:04d}-{safe_member.name}",
                    media_type=mimetypes_for_suffix(safe_member.suffix),
                    payload=image,
                    metadata={
                        "source_artifact_id": source.id,
                        "archive_member": str(safe_member),
                        "page": index,
                    },
                )
                page_ids.append(page.id)
                manifest_pages.append(
                    {"page": index, "artifact_id": page.id, "name": safe_member.name}
                )
                context.progress(index / len(image_members))
        manifest = context.create_artifact(
            kind="manga_manifest",
            filename="manga-manifest.json",
            media_type="application/json",
            payload=json.dumps(
                {
                    "version": 1,
                    "source_artifact_id": source.id,
                    "pages": manifest_pages,
                },
                ensure_ascii=False,
                indent=2,
            ).encode(),
            metadata={"page_count": len(page_ids)},
        )
        return StepResult([manifest.id, *page_ids])

    def _translate_manga(self, context: ExecutionContext) -> StepResult:
        if not context.job.adapter_id:
            raise LinguaError(ErrorCode.CONFIGURATION, "Manga Job has no configured Adapter")
        adapter = self.service.adapters.get(context.job.adapter_id, "manga_full_pipeline")
        health = adapter.health()
        if not health.available:
            raise LinguaError(
                ErrorCode.ADAPTER_UNAVAILABLE,
                health.message,
                health.details,
                retryable=True,
            )
        pages = [
            artifact for artifact in context.input_artifacts if artifact.kind == "manga_page_source"
        ]
        outputs: list[str] = []
        failures: list[LinguaError] = []
        for index, page in enumerate(pages, start=1):
            context.checkpoint()
            try:
                result = adapter.translate_image(
                    image=context.payload(page),
                    filename=page.filename,
                    source_language=context.job.source_language,
                    target_language=context.job.target_language,
                )
                image_artifact = context.create_artifact(
                    kind="manga_page_translated",
                    filename=f"translated-{page.filename}",
                    media_type=result.media_type,
                    payload=result.image,
                    metadata={
                        "source_page_artifact_id": page.id,
                        "adapter_id": adapter.manifest.id,
                        "page": index,
                    },
                )
                raw_artifact = context.create_artifact(
                    kind="adapter_raw_output",
                    filename=f"adapter-{index:04d}.json",
                    media_type="application/json",
                    payload=json.dumps(result.raw_metadata, ensure_ascii=False, indent=2).encode(),
                    metadata={"adapter_id": adapter.manifest.id, "page": index},
                )
                outputs.extend([image_artifact.id, raw_artifact.id])
            except LinguaError as exc:
                failures.append(exc)
                raw_artifact = context.create_artifact(
                    kind="adapter_raw_output",
                    filename=f"adapter-{index:04d}-error.json",
                    media_type="application/json",
                    payload=json.dumps(
                        {"error_code": exc.code, "message": exc.message},
                        ensure_ascii=False,
                        indent=2,
                    ).encode(),
                    metadata={"adapter_id": adapter.manifest.id, "page": index, "failed": True},
                )
                outputs.append(raw_artifact.id)
                context.log(
                    "ERROR",
                    "Manga page Adapter invocation failed",
                    {"page": index, "error_code": exc.code},
                )
            context.progress(index / max(len(pages), 1))
            context.checkpoint()
        translated_count = len(
            [
                row
                for row in self.service.artifact_rows(outputs)
                if row.kind == "manga_page_translated"
            ]
        )
        if translated_count == 0 and failures:
            raise failures[0]
        partial = None
        if failures:
            partial = LinguaError(
                failures[0].code,
                f"{len(failures)} of {len(pages)} manga pages failed",
                {"failed_pages": len(failures), "total_pages": len(pages)},
                retryable=True,
            )
        return StepResult(outputs, partial_error=partial)

    def _export_manga(self, context: ExecutionContext) -> StepResult:
        pages = [
            artifact
            for artifact in context.input_artifacts
            if artifact.kind == "manga_page_translated"
        ]
        if not pages:
            raise LinguaError(ErrorCode.OUTPUT_MISSING, "No translated manga pages to export")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, page in enumerate(pages, start=1):
                suffix = Path(page.filename).suffix.lower() or ".png"
                archive.writestr(f"{index:04d}{suffix}", context.payload(page))
        artifact = context.create_artifact(
            kind="manga_export_cbz",
            filename=f"{context.job.project_name}-translated.cbz",
            media_type="application/vnd.comicbook+zip",
            payload=buffer.getvalue(),
            metadata={"format": "cbz", "page_count": len(pages)},
        )
        return StepResult([artifact.id])


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def mimetypes_for_suffix(suffix: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix.lower(), "application/octet-stream")
