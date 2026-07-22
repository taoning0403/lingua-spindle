"""FastAPI interface over the shared application service."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, cast

try:
    import python_multipart as _multipart  # noqa: F401
    from fastapi import (
        FastAPI,
        File,
        Form,
        Header,
        Query,
        Request,
        Response,
        UploadFile,
    )
    from fastapi.exceptions import RequestValidationError
    from fastapi.openapi.utils import get_openapi
    from fastapi.responses import FileResponse, JSONResponse
    from pydantic import BaseModel, ConfigDict, Field
    from starlette.concurrency import run_in_threadpool
    from starlette.types import Message, Receive, Scope, Send
except ModuleNotFoundError as exc:  # pragma: no cover - isolated Wheel verification
    if exc.name not in {"fastapi", "python_multipart", "pydantic", "starlette"}:
        raise
    raise ModuleNotFoundError(
        "Headless HTTP server support is optional; install 'linguaspindle[server]'",
        name=exc.name,
    ) from exc

from .. import __version__
from ..application import ApplicationService
from ..config import Settings
from ..core import (
    BatchStatus,
    DocumentManifest,
    SourceFormat,
    TranslationOptions,
    TranslationStatus,
    inspect_document,
    rebuild_document,
    translate_segments,
)
from ..errors import ErrorCode, LinguaError
from ..idempotency import (
    IdempotencyClaim,
    IdempotencyContext,
    IdempotencyReplay,
    ServiceOperationResult,
    idempotency_context,
    normalize_request_id,
    normalized_text_mapping_hash,
    request_fingerprint,
)
from ..json_types import normalize_json_object
from ..orchestration.engine import JobRunner
from ..orchestration.state import JobStatus, StepStatus
from ..security import redact, redact_text

_LOGGER = logging.getLogger(__name__)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateJobRequest(StrictRequest):
    pipeline_key: str | None = None
    profile_id: str | None = None
    provider_id: str | None = None
    adapter_id: str | None = None


class CreateProfileRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=120)
    source_language: str = Field(min_length=1, max_length=40)
    target_language: str = Field(min_length=1, max_length=40)
    provider_id: Literal["mock", "openai-compatible"] = "mock"
    model: str | None = None
    style: str = "Preserve tone and paragraph structure."
    prompt_template: str | None = None
    prompt_version: str = "v1"
    batch_size: int = Field(default=8, ge=1, le=100)
    model_parameters: dict[str, Any] = Field(default_factory=dict)


class ProfileResponse(BaseModel):
    id: str
    name: str
    source_language: str
    target_language: str
    provider_id: str
    model: str
    style: str
    context_strategy: str
    prompt_template: str
    prompt_version: str
    batch_size: int
    model_parameters: dict[str, Any]
    created_at: str
    updated_at: str


class ErrorResponse(BaseModel):
    """Stable public application-error payload."""

    code: ErrorCode
    message: str
    details: dict[str, Any]
    retryable: bool


class ErrorEnvelope(BaseModel):
    error: ErrorResponse


class RecordedError(BaseModel):
    """Persisted Job or Step error, which has no retryability field."""

    code: ErrorCode
    message: str
    details: dict[str, Any]


class ArtifactResponse(BaseModel):
    id: str
    project_id: str
    job_id: str | None
    step_run_id: str | None
    kind: str
    filename: str
    media_type: str
    size: int
    checksum: str
    metadata: dict[str, Any]
    created_at: str
    download_url: str


class SourceResponse(BaseModel):
    id: str
    kind: str
    original_name: str
    media_type: str
    size: int
    checksum: str
    artifact_id: str
    metadata: dict[str, Any]
    created_at: str


class StepLogResponse(BaseModel):
    id: int
    level: str
    message: str
    details: dict[str, Any]
    created_at: str


class StepResponse(BaseModel):
    id: str
    key: str
    order: int
    capability: str
    executor_type: str
    executor_id: str | None
    status: StepStatus
    attempt_count: int
    progress: float
    started_at: str | None
    ended_at: str | None
    input_artifact_ids: list[str]
    output_artifact_ids: list[str]
    config_snapshot: dict[str, Any]
    error: RecordedError | None
    logs: list[StepLogResponse]


class JobSummaryResponse(BaseModel):
    id: str
    project_id: str
    pipeline_key: str
    provider_id: str
    adapter_id: str | None
    status: JobStatus
    progress: float
    control_request: Literal["pause", "cancel"] | None
    requested_at: str
    started_at: str | None
    ended_at: str | None
    error: RecordedError | None


class JobResponse(JobSummaryResponse):
    profile_snapshot: dict[str, Any]
    steps: list[StepResponse]
    artifacts: list[ArtifactResponse]


class ProjectSummaryResponse(BaseModel):
    id: str
    name: str
    kind: Literal["novel", "manga"]
    source_language: str
    target_language: str
    created_at: str
    updated_at: str
    latest_job: JobSummaryResponse | None


class ProjectResponse(ProjectSummaryResponse):
    sources: list[SourceResponse]
    jobs: list[JobSummaryResponse]
    artifacts: list[ArtifactResponse]


class ProjectDeletionImpact(BaseModel):
    sources: int
    jobs: int
    artifacts: int


class ProjectDeletionResponse(BaseModel):
    deleted: str
    impact: ProjectDeletionImpact
    cleanup_error: str | None


class SegmentLocatorResponse(BaseModel):
    kind: str
    document_path: str
    start: int | None = None
    end: int | None = None
    unit_sequence: int | None = None
    element_index: int | None = None
    slot: str | None = None
    attribute: str | None = None
    part_index: int | None = None
    part_count: int | None = None
    document_order: int | None = None
    document_type: str | None = None


class QaFindingResponse(BaseModel):
    category: str
    severity: str
    message: str


class SegmentErrorResponse(BaseModel):
    code: ErrorCode
    message: str


class SegmentResponse(BaseModel):
    """Stable source Segment plus optional state from a persisted runtime Job."""

    schema_version: Literal["segment.v1"]
    segment_id: str
    order: int
    sequence: int
    source_format: SourceFormat
    source_artifact_id: str
    source_document: str
    source_text: str
    content_role: str
    locator: SegmentLocatorResponse
    source_hash: str
    translation_input_hash: str
    joiner: str
    job_id: str | None = None
    status: str = TranslationStatus.SOURCE.value
    translated_text: str | None = None
    model: str | None = None
    reused_from_segment_id: str | None = None
    error: SegmentErrorResponse | None = None
    qa_findings: list[QaFindingResponse] = Field(default_factory=list)


class TranslateSegmentsRequest(StrictRequest):
    """Translate exactly the named Segments; an empty list is intentionally a no-op."""

    selected_segment_ids: list[str] = Field(max_length=512)
    existing_translations: dict[str, str] = Field(default_factory=dict, max_length=512)
    provider_id: str = Field(default="mock", min_length=1, max_length=120)
    style: str = Field(default="", max_length=4_000)
    prompt_version: str = Field(default="v1", min_length=1, max_length=120)
    concurrency: int = Field(default=1, ge=1, le=32)
    max_retries: int = Field(default=2, ge=0, le=20)
    retry_backoff_seconds: float = Field(default=0.25, ge=0, le=60)


class TranslationRecordResponse(BaseModel):
    schema_version: Literal["translation-record.v1"]
    segment_id: str
    order: int
    source_hash: str
    translation_input_hash: str
    status: TranslationStatus
    translated_text: str | None = None
    provider_id: str | None = None
    model: str | None = None
    attempts: int
    usage: dict[str, int] | None = None
    error: ErrorResponse | None = None


class TranslationBatchResponse(BaseModel):
    schema_version: Literal["translation-batch.v1"]
    status: BatchStatus
    source_sha256: str | None
    selected_segment_ids: list[str]
    records: list[TranslationRecordResponse]


class SelectedTranslationResponse(BaseModel):
    project_id: str
    source_artifact_id: str
    result: TranslationBatchResponse
    artifact: ArtifactResponse


class RebuildDocumentRequest(StrictRequest):
    """Caller-supplied translation text keyed by stable Segment ID."""

    translations: dict[str, str] = Field(default_factory=dict, max_length=100_000)


class BuildResultResponse(BaseModel):
    schema_version: Literal["build-result.v1"]
    source_format: SourceFormat
    output_sha256: str
    output_size: int
    translated_count: int
    preserved_count: int
    details: dict[str, Any]


class RebuildDocumentResponse(BaseModel):
    project_id: str
    source_artifact_id: str
    build: BuildResultResponse
    artifact: ArtifactResponse


@dataclass(frozen=True, slots=True)
class _NovelSourceContext:
    project_id: str
    source_artifact_id: str
    source_name: str
    source_path: Path
    source_language: str
    target_language: str
    manifest: DocumentManifest


_STABLE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": ErrorEnvelope,
        "description": "Invalid input or another normalized application error",
    },
    404: {"model": ErrorEnvelope, "description": "Requested resource was not found"},
    409: {
        "model": ErrorEnvelope,
        "description": "Requested operation conflicts with the current durable state",
    },
    413: {
        "model": ErrorEnvelope,
        "description": "Upload or expanded archive exceeds a configured resource limit",
    },
    422: {
        "model": ErrorEnvelope,
        "description": "Request validation failed before the application operation ran",
    },
    429: {"model": ErrorEnvelope, "description": "Provider rate limit was reached"},
    500: {"model": ErrorEnvelope, "description": "An unexpected normalized error occurred"},
    502: {"model": ErrorEnvelope, "description": "Provider or Adapter request failed"},
    503: {"model": ErrorEnvelope, "description": "Provider or Adapter is unavailable"},
    504: {"model": ErrorEnvelope, "description": "Provider or Adapter request timed out"},
}

_IDEMPOTENCY_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_STABLE_ERROR_RESPONSES,
    428: {
        "model": ErrorEnvelope,
        "description": "Idempotency-Key is required by server configuration",
    },
}

_IDEMPOTENCY_RESPONSE_HEADERS: dict[str, dict[str, Any]] = {
    "Idempotency-Replayed": {
        "description": "True only when the response reuses a completed idempotent result",
        "schema": {"type": "string", "enum": ["true", "false"]},
    },
    "Location": {
        "description": "Canonical API location of the created or reused resource",
        "schema": {"type": "string"},
    },
}

_JOB_RESPONSE_HEADERS: dict[str, dict[str, Any]] = {
    **_IDEMPOTENCY_RESPONSE_HEADERS,
    "X-Job-Coalesced": {
        "description": "True when an equivalent active Job was reused",
        "schema": {"type": "string", "enum": ["true", "false"]},
    },
}

IdempotencyKeyHeader = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        description=(
            "Caller-chosen 8-128 character idempotency key. The server stores only its SHA-256."
        ),
    ),
]


class RequestCorrelationMiddleware:
    """Attach one sanitized request ID to every success and error response."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied = headers.get(b"x-request-id")
        request_id = normalize_request_id(
            supplied.decode("ascii", errors="ignore") if supplied is not None else None
        )
        state = scope.setdefault("state", {})
        state["request_id"] = request_id

        async def correlated_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, correlated_send)


class UploadBodyLimitMiddleware:
    """Bound mutating request bodies before FastAPI parses their content."""

    def __init__(self, app: Callable[..., Awaitable[None]], *, maximum_bytes: int) -> None:
        self.app = app
        self.maximum_bytes = maximum_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_content_length = headers.get(b"content-length")
        if raw_content_length is not None:
            try:
                content_length = int(raw_content_length)
            except ValueError:
                content_length = None
            if content_length is not None and content_length > self.maximum_bytes:
                await self._reject(scope, receive, send)
                return

        received = 0
        too_large = False
        buffered_response: list[Message] = []

        async def limited_receive() -> Message:
            nonlocal received, too_large
            if too_large:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.maximum_bytes:
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        async def buffered_send(message: Message) -> None:
            buffered_response.append(message)

        try:
            await self.app(scope, limited_receive, buffered_send)
        except Exception:
            if not too_large:
                raise
        if too_large:
            await self._reject(scope, receive, send)
            return
        for message in buffered_response:
            await send(message)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": ErrorCode.UPLOAD_TOO_LARGE,
                    "message": "Request body exceeds the configured size limit",
                    "details": {"maximum_request_bytes": self.maximum_bytes},
                    "retryable": False,
                }
            },
        )
        await response(scope, receive, send)


def _service(request: Request) -> ApplicationService:
    return cast(ApplicationService, request.app.state.service)


def _status_for_error(error: LinguaError) -> int:
    return {
        ErrorCode.NOT_FOUND: 404,
        ErrorCode.INVALID_STATE: 409,
        ErrorCode.IDEMPOTENCY_KEY_REQUIRED: 428,
        ErrorCode.IDEMPOTENCY_KEY_INVALID: 400,
        ErrorCode.IDEMPOTENCY_CONFLICT: 409,
        ErrorCode.IDEMPOTENCY_IN_PROGRESS: 409,
        ErrorCode.IDEMPOTENCY_INDETERMINATE: 409,
        ErrorCode.ADAPTER_UNAVAILABLE: 503,
        ErrorCode.TIMEOUT: 504,
        ErrorCode.MODEL_API: 502,
        ErrorCode.RATE_LIMIT: 429,
        ErrorCode.UPLOAD_TOO_LARGE: 413,
        ErrorCode.ARCHIVE_LIMIT_EXCEEDED: 413,
        ErrorCode.UNKNOWN: 500,
    }.get(error.code, 400)


def _request_id(request: Request) -> str:
    return str(request.state.request_id)


def _idempotency(
    request: Request,
    key: str | None,
) -> IdempotencyContext | None:
    service = _service(request)
    return idempotency_context(
        key,
        request_id=_request_id(request),
        required=service.settings.require_idempotency_key,
    )


def _operation_headers(
    response: Response,
    result: ServiceOperationResult,
    *,
    location: str,
    success_status: int,
    job: bool = False,
) -> None:
    response.status_code = 200 if result.replayed or result.coalesced else success_status
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    response.headers["Location"] = location
    if job:
        response.headers["X-Job-Coalesced"] = str(result.coalesced).lower()


def _operation_options(
    service: ApplicationService,
    context: _NovelSourceContext | None = None,
    body: TranslateSegmentsRequest | None = None,
    *,
    source_language: str | None = None,
    target_language: str | None = None,
) -> TranslationOptions:
    return TranslationOptions(
        source_language=source_language or (context.source_language if context else "auto"),
        target_language=target_language or (context.target_language if context else "en"),
        style=body.style if body else "",
        prompt_version=body.prompt_version if body else "v1",
        concurrency=body.concurrency if body else 1,
        max_retries=body.max_retries if body else 2,
        retry_backoff_seconds=body.retry_backoff_seconds if body else 0.25,
        max_source_bytes=service.settings.max_upload_bytes,
    )


def _novel_source_context(
    service: ApplicationService,
    project_id: str,
    *,
    body: TranslateSegmentsRequest | None = None,
) -> _NovelSourceContext:
    project = service.get_project(project_id)
    if project["kind"] != "novel":
        raise LinguaError(
            ErrorCode.INVALID_FORMAT,
            "Novel Segment operations require a novel Project",
        )
    sources = cast(list[dict[str, Any]], project.get("sources", []))
    if not sources:
        raise LinguaError(ErrorCode.NOT_FOUND, "Project source not found")
    source = max(sources, key=lambda item: str(item.get("created_at", "")))
    source_kind = str(source.get("kind", ""))
    if source_kind not in {"txt", "epub"}:
        raise LinguaError(
            ErrorCode.INVALID_FORMAT,
            "Novel Segment operations support only TXT and EPUB Sources",
            {"source_kind": source_kind},
        )
    source_artifact_id = str(source["artifact_id"])
    artifact, source_path = service.artifact_path(source_artifact_id)
    if artifact["project_id"] != project_id:
        raise LinguaError(ErrorCode.SOURCE_MISMATCH, "Source Artifact belongs to another Project")
    source_name = str(source["original_name"])
    source_language = str(project["source_language"])
    target_language = str(project["target_language"])
    options = _operation_options(
        service,
        body=body,
        source_language=source_language,
        target_language=target_language,
    )
    manifest = inspect_document(
        source_path,
        filename=source_name,
        format_hint=source_kind,
        options=options,
        archive_limits=service.settings.archive_limits(),
    )
    return _NovelSourceContext(
        project_id=project_id,
        source_artifact_id=source_artifact_id,
        source_name=source_name,
        source_path=source_path,
        source_language=source_language,
        target_language=target_language,
        manifest=manifest,
    )


def _segment_payloads(
    service: ApplicationService,
    context: _NovelSourceContext,
    job_id: str | None,
) -> list[dict[str, Any]]:
    if job_id is not None:
        job = service.get_job(job_id)
        if job["project_id"] != context.project_id:
            raise LinguaError(ErrorCode.NOT_FOUND, "Job does not belong to this Project")
    runtime_rows = service.list_segments(context.project_id, job_id=job_id)
    by_id = {str(item.get("segment_id")): item for item in runtime_rows}
    by_source = {
        (int(item.get("sequence", -1)), str(item.get("source_text", ""))): item
        for item in runtime_rows
    }
    payloads: list[dict[str, Any]] = []
    for segment in context.manifest.segments:
        state = by_id.get(segment.segment_id) or by_source.get((segment.order, segment.source_text))
        value = cast(dict[str, Any], segment.to_dict())
        value.update(
            {
                "sequence": segment.order,
                "source_artifact_id": context.source_artifact_id,
                "job_id": state.get("job_id") if state else None,
                "status": state.get("status", TranslationStatus.SOURCE.value)
                if state
                else TranslationStatus.SOURCE.value,
                "translated_text": state.get("translated_text") if state else None,
                "model": state.get("model") if state else None,
                "reused_from_segment_id": (state.get("reused_from_segment_id") if state else None),
                "error": state.get("error") if state else None,
                "qa_findings": state.get("qa_findings", []) if state else [],
            }
        )
        payloads.append(value)
    return payloads


def _reject_runtime_secret(service: ApplicationService, value: object) -> None:
    secret = service.settings.openai_api_key
    if secret and secret in json.dumps(value, ensure_ascii=False, default=str):
        raise LinguaError(
            ErrorCode.CONFIGURATION,
            "Request contains the runtime Provider secret; remove it before submission",
        )


def _artifact_stem(source_name: str) -> str:
    stem = Path(source_name).stem or "document"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.") or "document"


def _translate_selected_segments(
    service: ApplicationService,
    project_id: str,
    body: TranslateSegmentsRequest,
    idempotency: IdempotencyContext | None = None,
) -> ServiceOperationResult:
    _reject_runtime_secret(service, body.model_dump())
    context = _novel_source_context(service, project_id, body=body)
    manifest_ids = {segment.segment_id for segment in context.manifest.segments}
    unknown_ids = sorted(
        (set(body.selected_segment_ids) | set(body.existing_translations)) - manifest_ids
    )
    if unknown_ids:
        raise LinguaError(
            ErrorCode.SEGMENT_NOT_FOUND,
            "Selected Segment ID is not present in the manifest",
            {"unknown_segment_ids": unknown_ids},
        )
    options = _operation_options(service, context, body)
    provider = service.providers.get(body.provider_id)
    claim: IdempotencyClaim | None = None
    if idempotency is not None:
        selected = set(body.selected_segment_ids)
        ordered_segment_ids = [
            segment.segment_id
            for segment in context.manifest.segments
            if segment.segment_id in selected
        ]
        fingerprint_value = request_fingerprint(
            "selected-translation",
            {
                "project_id": project_id,
                "source_artifact_id": context.source_artifact_id,
                "source_sha256": context.manifest.source_sha256,
                "ordered_segment_ids": ordered_segment_ids,
                "existing_translations_sha256": normalized_text_mapping_hash(
                    body.existing_translations
                ),
                "provider": service.provider_execution_config(body.provider_id),
                "source_language": context.source_language,
                "target_language": context.target_language,
                "style": body.style,
                "prompt_version": body.prompt_version,
                "concurrency": body.concurrency,
                "max_retries": body.max_retries,
                "retry_backoff_seconds": body.retry_backoff_seconds,
            },
        )
        reserved = service.reserve_idempotency(
            scope=f"projects:{project_id}:segments:translate",
            request_fingerprint_value=fingerprint_value,
            context=idempotency,
        )
        if isinstance(reserved, IdempotencyReplay):
            artifact_payload = service.idempotent_resource(reserved)
            try:
                _, stored_result = service.read_artifact(reserved.resource_id)
                result_payload = json.loads(stored_result)
            except (LinguaError, json.JSONDecodeError, UnicodeDecodeError) as error:
                raise LinguaError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "The translation result retained by this Idempotency-Key is unavailable",
                ) from error
            return ServiceOperationResult(
                {
                    "project_id": project_id,
                    "source_artifact_id": artifact_payload["metadata"]["source_artifact_id"],
                    "result": result_payload,
                    "artifact": artifact_payload,
                },
                replayed=True,
            )
        claim = reserved
    try:
        result = translate_segments(
            context.manifest,
            provider,
            options,
            selected_segment_ids=body.selected_segment_ids,
            existing_translations=body.existing_translations,
            sensitive_values=(service.settings.openai_api_key or "",),
        )
        payload = json.dumps(result.to_dict(), ensure_ascii=False, indent=2).encode("utf-8")
        artifact = service.create_artifact(
            project_id=project_id,
            kind="novel_translations",
            filename=f"{_artifact_stem(context.source_name)}.translation-batch.json",
            media_type="application/json",
            payload=payload,
            metadata={
                "schema_version": result.schema_version,
                "source_artifact_id": context.source_artifact_id,
                "source_sha256": context.manifest.source_sha256,
                "status": result.status.value,
                "selected_segment_ids": list(result.selected_segment_ids),
            },
        )
    except BaseException:
        if claim is not None:
            service.mark_idempotency_indeterminate(claim)
        raise
    value = {
        "project_id": project_id,
        "source_artifact_id": context.source_artifact_id,
        "result": result.to_dict(),
        "artifact": service.get_artifact(artifact.id),
    }
    if claim is not None:
        try:
            service.complete_idempotency(
                claim,
                resource_type="artifact",
                resource_id=artifact.id,
                response_status=200,
                result_reference={
                    "project_id": project_id,
                    "source_artifact_id": context.source_artifact_id,
                },
            )
        except BaseException:
            service.mark_idempotency_indeterminate(claim)
            raise
    return ServiceOperationResult(value)


def _rebuild_from_external_translations(
    service: ApplicationService,
    project_id: str,
    body: RebuildDocumentRequest,
    idempotency: IdempotencyContext | None = None,
) -> ServiceOperationResult:
    _reject_runtime_secret(service, body.model_dump())
    context = _novel_source_context(service, project_id)
    manifest_ids = {segment.segment_id for segment in context.manifest.segments}
    unknown_ids = sorted(set(body.translations) - manifest_ids)
    if unknown_ids:
        raise LinguaError(
            ErrorCode.SEGMENT_NOT_FOUND,
            "Selected Segment ID is not present in the manifest",
            {"unknown_segment_ids": unknown_ids},
        )
    is_epub = context.manifest.source_format in {SourceFormat.EPUB2, SourceFormat.EPUB3}
    suffix = ".epub" if is_epub else ".txt"
    media_type = "application/epub+zip" if is_epub else "text/plain; charset=utf-8"
    kind = "novel_export_epub" if is_epub else "novel_export_txt"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="linguaspindle-api-rebuild-", suffix=suffix
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    claim: IdempotencyClaim | None = None
    if idempotency is not None:
        ordered_segment_ids = [
            segment.segment_id
            for segment in context.manifest.segments
            if segment.segment_id in body.translations
        ]
        fingerprint_value = request_fingerprint(
            "document-rebuild",
            {
                "project_id": project_id,
                "source_artifact_id": context.source_artifact_id,
                "source_sha256": context.manifest.source_sha256,
                "ordered_segment_ids": ordered_segment_ids,
                "translations_sha256": normalized_text_mapping_hash(body.translations),
                "target_format": context.manifest.source_format.value,
                "target_language": context.target_language,
            },
        )
        reserved = service.reserve_idempotency(
            scope=f"projects:{project_id}:rebuild",
            request_fingerprint_value=fingerprint_value,
            context=idempotency,
        )
        if isinstance(reserved, IdempotencyReplay):
            artifact_payload = service.idempotent_resource(reserved)
            try:
                service.artifact_path(reserved.resource_id)
                metadata = cast(dict[str, Any], artifact_payload["metadata"])
                build_payload = cast(dict[str, Any], metadata["build"])
                source_artifact_id = str(metadata["source_artifact_id"])
            except (KeyError, LinguaError, TypeError) as error:
                raise LinguaError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "The rebuild result retained by this Idempotency-Key is unavailable",
                ) from error
            temporary_path.unlink(missing_ok=True)
            return ServiceOperationResult(
                {
                    "project_id": project_id,
                    "source_artifact_id": source_artifact_id,
                    "build": build_payload,
                    "artifact": artifact_payload,
                },
                replayed=True,
            )
        claim = reserved
    try:
        build = rebuild_document(
            context.source_path,
            context.manifest,
            body.translations,
            temporary_path,
            target_language=context.target_language,
            overwrite=True,
            archive_limits=service.settings.archive_limits(),
        )
        artifact = service.create_artifact_from_path(
            project_id=project_id,
            kind=kind,
            filename=(
                f"{_artifact_stem(context.source_name)}.translated."
                f"{re.sub(r'[^A-Za-z0-9._-]+', '-', context.target_language)}{suffix}"
            ),
            media_type=media_type,
            source_path=temporary_path,
            metadata={
                "schema_version": "external-translation-rebuild.v1",
                "source_artifact_id": context.source_artifact_id,
                "source_sha256": context.manifest.source_sha256,
                "translation_segment_ids": sorted(body.translations),
                "build": build.to_dict(),
            },
        )
    except BaseException:
        if claim is not None:
            service.mark_idempotency_indeterminate(claim)
        raise
    finally:
        temporary_path.unlink(missing_ok=True)
    value = {
        "project_id": project_id,
        "source_artifact_id": context.source_artifact_id,
        "build": build.to_dict(),
        "artifact": service.get_artifact(artifact.id),
    }
    if claim is not None:
        try:
            service.complete_idempotency(
                claim,
                resource_type="artifact",
                resource_id=artifact.id,
                response_status=200,
                result_reference={
                    "project_id": project_id,
                    "source_artifact_id": context.source_artifact_id,
                },
            )
        except BaseException:
            service.mark_idempotency_indeterminate(claim)
            raise
    return ServiceOperationResult(value)


def create_app(settings: Settings | None = None, *, start_worker: bool = True) -> FastAPI:
    runtime_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        service = ApplicationService(runtime_settings)
        runner = JobRunner(service)
        app.state.service = service
        app.state.runner = runner
        if start_worker:
            runner.start(recover=True)
        try:
            yield
        finally:
            runner.stop()
            service.close()

    app = FastAPI(
        title="LinguaSpindle API",
        version=__version__,
        description=(
            "Instance-scoped asynchronous translation orchestration. "
            "The API has no login or account model and binds to loopback by default."
        ),
        lifespan=lifespan,
        openapi_tags=[
            {"name": "system", "description": "Health and runtime capabilities"},
            {"name": "projects", "description": "Projects, immutable Sources, and results"},
            {
                "name": "documents",
                "description": "Stable novel Segments, selected translation, and reconstruction",
            },
            {"name": "jobs", "description": "Persistent asynchronous Jobs and controls"},
            {"name": "artifacts", "description": "Artifact metadata and payload downloads"},
        ],
    )
    # Multipart framing adds a small amount to the source payload. The application layer still
    # enforces the exact source-file limit while this outer guard prevents unbounded parser I/O.
    app.add_middleware(
        UploadBodyLimitMiddleware,
        maximum_bytes=runtime_settings.max_upload_bytes + 1024 * 1024,
    )
    app.add_middleware(RequestCorrelationMiddleware)

    @app.exception_handler(LinguaError)
    async def handle_lingua_error(request: Request, error: LinguaError) -> JSONResponse:
        known = [runtime_settings.openai_api_key or ""]
        request_id = _request_id(request)
        _LOGGER.warning(
            "Request failed request_id=%s error_code=%s",
            request_id,
            error.code.value,
        )
        headers = None
        if error.code == ErrorCode.IDEMPOTENCY_IN_PROGRESS:
            retry_after = int((error.details or {}).get("retry_after_seconds", 1))
            headers = {"Retry-After": str(max(retry_after, 1))}
        return JSONResponse(
            status_code=_status_for_error(error),
            headers=headers,
            content={
                "error": {
                    "code": error.code,
                    "message": redact_text(error.message, known),
                    "details": normalize_json_object(redact(error.details or {}, known)),
                    "retryable": error.retryable,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        _LOGGER.warning(
            "Request validation failed request_id=%s",
            _request_id(request),
        )
        validation = [
            {key: value for key, value in item.items() if key not in {"input", "ctx"}}
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": ErrorCode.CONFIGURATION,
                    "message": "Request validation failed",
                    "details": {"validation": validation},
                    "retryable": False,
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        _LOGGER.error(
            "Unexpected request failure request_id=%s exception_type=%s",
            _request_id(request),
            type(error).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": ErrorCode.UNKNOWN,
                    "message": "Unexpected server error",
                    "details": {"exception_type": type(error).__name__},
                    "retryable": False,
                }
            },
        )

    @app.get("/health", tags=["system"], summary="Process and database health")
    async def health(request: Request) -> dict[str, Any]:
        return _service(request).health()

    @app.get("/api/system", tags=["system"])
    async def system(request: Request) -> dict[str, Any]:
        return _service(request).system_summary()

    @app.get("/api/adapters", tags=["system"])
    async def adapters(request: Request) -> list[dict[str, Any]]:
        return _service(request).adapter_statuses()

    @app.get("/api/providers", tags=["system"])
    async def providers(request: Request) -> list[dict[str, Any]]:
        return _service(request).provider_statuses()

    @app.get("/api/pipelines", tags=["system"])
    async def pipelines(request: Request) -> list[dict[str, object]]:
        return _service(request).pipeline_catalog()

    @app.get("/api/profiles", tags=["system"])
    async def profiles(request: Request) -> list[dict[str, Any]]:
        return _service(request).list_profiles()

    @app.post(
        "/api/profiles",
        tags=["system"],
        status_code=201,
        response_model=ProfileResponse,
        responses={
            200: {
                "model": ProfileResponse,
                "description": "Completed idempotent Profile replay",
                "headers": _IDEMPOTENCY_RESPONSE_HEADERS,
            },
            201: {
                "model": ProfileResponse,
                "description": "Profile created",
                "headers": _IDEMPOTENCY_RESPONSE_HEADERS,
            },
            **_IDEMPOTENCY_ERROR_RESPONSES,
        },
    )
    async def create_profile(
        request: Request,
        response: Response,
        body: CreateProfileRequest,
        idempotency_key: IdempotencyKeyHeader = None,
    ) -> dict[str, Any]:
        result = _service(request).create_profile_operation(
            **body.model_dump(),
            idempotency=_idempotency(request, idempotency_key),
            request_id=_request_id(request),
        )
        _operation_headers(
            response,
            result,
            location=f"/api/profiles/{result.value['id']}",
            success_status=201,
        )
        return result.value

    @app.get(
        "/api/profiles/{profile_id}",
        tags=["system"],
        response_model=ProfileResponse,
        responses=_STABLE_ERROR_RESPONSES,
    )
    async def get_profile(request: Request, profile_id: str) -> dict[str, Any]:
        return _service(request).get_profile(profile_id)

    @app.post(
        "/api/projects",
        tags=["projects"],
        status_code=201,
        response_model=ProjectResponse,
        responses={
            200: {
                "model": ProjectResponse,
                "description": "Completed idempotent Project replay",
                "headers": _IDEMPOTENCY_RESPONSE_HEADERS,
            },
            201: {
                "model": ProjectResponse,
                "description": "Project and immutable Source created",
                "headers": _IDEMPOTENCY_RESPONSE_HEADERS,
            },
            **_IDEMPOTENCY_ERROR_RESPONSES,
        },
    )
    async def create_project(
        request: Request,
        response: Response,
        name: Annotated[str, Form(min_length=1, max_length=200)],
        kind: Annotated[Literal["novel", "manga"], Form()],
        source_language: Annotated[str, Form(min_length=1, max_length=40)],
        target_language: Annotated[str, Form(min_length=1, max_length=40)],
        source: Annotated[
            UploadFile,
            File(description="TXT, EPUB 2/3, CBZ/ZIP, or one PNG/JPEG/WebP image"),
        ],
        idempotency_key: IdempotencyKeyHeader = None,
    ) -> dict[str, Any]:
        service = _service(request)
        result = await run_in_threadpool(
            service.create_project_from_stream_operation,
            name=name,
            kind=kind,
            source_language=source_language,
            target_language=target_language,
            source_name=source.filename or "source.bin",
            source=source.file,
            media_type=source.content_type,
            idempotency=_idempotency(request, idempotency_key),
            request_id=_request_id(request),
        )
        _operation_headers(
            response,
            result,
            location=f"/api/projects/{result.value['id']}",
            success_status=201,
        )
        return result.value

    @app.get(
        "/api/projects",
        tags=["projects"],
        response_model=list[ProjectSummaryResponse],
        responses=_STABLE_ERROR_RESPONSES,
    )
    async def list_projects(request: Request) -> list[dict[str, Any]]:
        return _service(request).list_projects()

    @app.get(
        "/api/projects/{project_id}",
        tags=["projects"],
        response_model=ProjectResponse,
        responses=_STABLE_ERROR_RESPONSES,
    )
    async def get_project(request: Request, project_id: str) -> dict[str, Any]:
        return _service(request).get_project(project_id)

    @app.delete(
        "/api/projects/{project_id}",
        tags=["projects"],
        response_model=ProjectDeletionResponse,
        responses=_STABLE_ERROR_RESPONSES,
    )
    async def delete_project(
        request: Request,
        project_id: str,
        confirmed: Annotated[
            bool, Query(description="Must be true after reviewing deletion impact")
        ] = False,
    ) -> dict[str, Any]:
        return _service(request).delete_project(project_id, confirmed=confirmed)

    @app.post(
        "/api/projects/{project_id}/jobs",
        tags=["jobs"],
        status_code=202,
        response_model=JobResponse,
        responses={
            200: {
                "model": JobResponse,
                "description": "Completed replay or equivalent active Job",
                "headers": _JOB_RESPONSE_HEADERS,
            },
            202: {
                "model": JobResponse,
                "description": "New Job queued",
                "headers": _JOB_RESPONSE_HEADERS,
            },
            **_IDEMPOTENCY_ERROR_RESPONSES,
        },
    )
    async def create_job(
        request: Request,
        response: Response,
        project_id: str,
        body: CreateJobRequest,
        idempotency_key: IdempotencyKeyHeader = None,
    ) -> dict[str, Any]:
        result = _service(request).create_job_operation(
            project_id=project_id,
            **body.model_dump(),
            idempotency=_idempotency(request, idempotency_key),
            request_id=_request_id(request),
        )
        _operation_headers(
            response,
            result,
            location=f"/api/jobs/{result.value['id']}",
            success_status=202,
            job=True,
        )
        return result.value

    @app.get(
        "/api/jobs",
        tags=["jobs"],
        response_model=list[JobSummaryResponse],
        responses=_STABLE_ERROR_RESPONSES,
    )
    async def list_jobs(
        request: Request,
        project_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return _service(request).list_jobs(project_id=project_id, status=status)

    @app.get(
        "/api/jobs/{job_id}",
        tags=["jobs"],
        response_model=JobResponse,
        responses=_STABLE_ERROR_RESPONSES,
    )
    async def get_job(request: Request, job_id: str) -> dict[str, Any]:
        return _service(request).get_job(job_id)

    @app.post(
        "/api/jobs/{job_id}/pause",
        tags=["jobs"],
        response_model=JobResponse,
        responses=_STABLE_ERROR_RESPONSES,
    )
    async def pause_job(request: Request, job_id: str) -> dict[str, Any]:
        return _service(request).pause_job(job_id)

    @app.post(
        "/api/jobs/{job_id}/resume",
        tags=["jobs"],
        response_model=JobResponse,
        responses=_STABLE_ERROR_RESPONSES,
    )
    async def resume_job(request: Request, job_id: str) -> dict[str, Any]:
        return _service(request).resume_job(job_id)

    @app.post(
        "/api/jobs/{job_id}/cancel",
        tags=["jobs"],
        response_model=JobResponse,
        responses=_STABLE_ERROR_RESPONSES,
    )
    async def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
        return _service(request).cancel_job(job_id)

    @app.post(
        "/api/jobs/{job_id}/retry",
        tags=["jobs"],
        response_model=JobResponse,
        responses={
            200: {
                "model": JobResponse,
                "description": "Job retry transition or completed replay",
                "headers": _IDEMPOTENCY_RESPONSE_HEADERS,
            },
            **_IDEMPOTENCY_ERROR_RESPONSES,
        },
    )
    async def retry_job(
        request: Request,
        response: Response,
        job_id: str,
        idempotency_key: IdempotencyKeyHeader = None,
    ) -> dict[str, Any]:
        result = _service(request).retry_job_operation(
            job_id,
            idempotency=_idempotency(request, idempotency_key),
        )
        _operation_headers(
            response,
            result,
            location=f"/api/jobs/{result.value['id']}",
            success_status=200,
        )
        return result.value

    @app.get(
        "/api/projects/{project_id}/artifacts",
        tags=["artifacts"],
        response_model=list[ArtifactResponse],
        responses=_STABLE_ERROR_RESPONSES,
    )
    async def list_artifacts(
        request: Request, project_id: str, job_id: str | None = None
    ) -> list[dict[str, Any]]:
        return _service(request).list_artifacts(project_id=project_id, job_id=job_id)

    @app.get(
        "/api/artifacts/{artifact_id}",
        tags=["artifacts"],
        response_model=ArtifactResponse,
        responses=_STABLE_ERROR_RESPONSES,
    )
    async def get_artifact(request: Request, artifact_id: str) -> dict[str, Any]:
        return _service(request).get_artifact(artifact_id)

    @app.get(
        "/api/artifacts/{artifact_id}/download",
        tags=["artifacts"],
        response_class=FileResponse,
        responses={
            200: {
                "description": "Immutable Artifact payload",
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                },
                "headers": {
                    "Content-Disposition": {
                        "description": "Attachment filename derived from Artifact metadata",
                        "schema": {"type": "string"},
                    },
                    "X-Content-Type-Options": {
                        "description": "Always nosniff",
                        "schema": {"type": "string", "enum": ["nosniff"]},
                    },
                },
            },
            **_STABLE_ERROR_RESPONSES,
        },
    )
    async def download_artifact(request: Request, artifact_id: str) -> FileResponse:
        metadata, path = _service(request).artifact_path(artifact_id)
        return FileResponse(
            path=path,
            media_type=metadata["media_type"],
            filename=metadata["filename"],
            headers={
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post(
        "/api/projects/{project_id}/exports",
        tags=["artifacts"],
        response_model=list[ArtifactResponse],
        responses=_STABLE_ERROR_RESPONSES,
    )
    async def export_project(
        request: Request, project_id: str, format_name: str | None = None
    ) -> list[dict[str, Any]]:
        return _service(request).export_project(project_id, format_name=format_name)

    @app.get(
        "/api/projects/{project_id}/segments",
        tags=["documents"],
        response_model=list[SegmentResponse],
        responses=_STABLE_ERROR_RESPONSES,
    )
    async def list_segments(
        request: Request, project_id: str, job_id: str | None = None
    ) -> list[dict[str, Any]]:
        service = _service(request)
        context = await run_in_threadpool(_novel_source_context, service, project_id)
        return await run_in_threadpool(_segment_payloads, service, context, job_id)

    @app.post(
        "/api/projects/{project_id}/segments/translate",
        tags=["documents"],
        response_model=SelectedTranslationResponse,
        responses={
            200: {
                "model": SelectedTranslationResponse,
                "description": "Selected translation result or completed replay",
                "headers": _IDEMPOTENCY_RESPONSE_HEADERS,
            },
            **_IDEMPOTENCY_ERROR_RESPONSES,
        },
    )
    async def translate_selected_project_segments(
        request: Request,
        response: Response,
        project_id: str,
        body: TranslateSegmentsRequest,
        idempotency_key: IdempotencyKeyHeader = None,
    ) -> dict[str, Any]:
        """Translate only explicit stable Segment IDs and persist the JSON result Artifact."""

        result = await run_in_threadpool(
            _translate_selected_segments,
            _service(request),
            project_id,
            body,
            _idempotency(request, idempotency_key),
        )
        _operation_headers(
            response,
            result,
            location=f"/api/artifacts/{result.value['artifact']['id']}",
            success_status=200,
        )
        return result.value

    @app.post(
        "/api/projects/{project_id}/rebuild",
        tags=["documents"],
        response_model=RebuildDocumentResponse,
        responses={
            200: {
                "model": RebuildDocumentResponse,
                "description": "Rebuilt Artifact or completed replay",
                "headers": _IDEMPOTENCY_RESPONSE_HEADERS,
            },
            **_IDEMPOTENCY_ERROR_RESPONSES,
        },
    )
    async def rebuild_project_document(
        request: Request,
        response: Response,
        project_id: str,
        body: RebuildDocumentRequest,
        idempotency_key: IdempotencyKeyHeader = None,
    ) -> dict[str, Any]:
        """Rebuild from the immutable Source using only caller-supplied Segment text."""

        result = await run_in_threadpool(
            _rebuild_from_external_translations,
            _service(request),
            project_id,
            body,
            _idempotency(request, idempotency_key),
        )
        _operation_headers(
            response,
            result,
            location=f"/api/artifacts/{result.value['artifact']['id']}",
            success_status=200,
        )
        return result.value

    @app.get("/", include_in_schema=False)
    async def headless_root() -> dict[str, str]:
        return {
            "name": "LinguaSpindle",
            "version": __version__,
            "mode": "headless",
            "health": "/health",
            "docs": "/docs",
            "openapi": "/openapi.json",
        }

    def correlated_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        request_parameter = {
            "name": "X-Request-ID",
            "in": "header",
            "required": False,
            "description": (
                "Optional 1-128 character correlation ID using letters, numbers, dot, "
                "underscore, colon, or hyphen. Invalid values are replaced safely."
            ),
            "schema": {"type": "string", "maxLength": 128},
        }
        response_header = {
            "description": "Sanitized caller correlation ID or a server-generated UUID",
            "schema": {"type": "string"},
        }
        for path_item in schema.get("paths", {}).values():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                    continue
                if not isinstance(operation, dict):
                    continue
                parameters = operation.setdefault("parameters", [])
                if not any(
                    isinstance(parameter, dict)
                    and parameter.get("in") == "header"
                    and str(parameter.get("name", "")).lower() == "x-request-id"
                    for parameter in parameters
                ):
                    parameters.append(request_parameter)
                for response_spec in operation.get("responses", {}).values():
                    if isinstance(response_spec, dict):
                        response_spec.setdefault("headers", {})["X-Request-ID"] = response_header
        app.openapi_schema = schema
        return schema

    app.openapi = correlated_openapi  # type: ignore[method-assign]

    return app
