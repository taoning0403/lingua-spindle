"""FastAPI interface over the shared application service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .. import __version__
from ..application import ApplicationService
from ..config import Settings
from ..errors import ErrorCode, LinguaError
from ..orchestration.engine import JobRunner
from ..security import redact, redact_text


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


def _service(request: Request) -> ApplicationService:
    return cast(ApplicationService, request.app.state.service)


def _status_for_error(error: LinguaError) -> int:
    return {
        ErrorCode.NOT_FOUND: 404,
        ErrorCode.INVALID_STATE: 409,
        ErrorCode.ADAPTER_UNAVAILABLE: 503,
        ErrorCode.TIMEOUT: 504,
        ErrorCode.MODEL_API: 502,
        ErrorCode.RATE_LIMIT: 429,
        ErrorCode.UNKNOWN: 500,
    }.get(error.code, 400)


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
            {"name": "jobs", "description": "Persistent asynchronous Jobs and controls"},
            {"name": "artifacts", "description": "Artifact metadata and payload downloads"},
        ],
    )

    @app.exception_handler(LinguaError)
    async def handle_lingua_error(_request: Request, error: LinguaError) -> JSONResponse:
        known = [runtime_settings.openai_api_key or ""]
        return JSONResponse(
            status_code=_status_for_error(error),
            content={
                "error": {
                    "code": error.code,
                    "message": redact_text(error.message, known),
                    "details": redact(error.details or {}, known),
                    "retryable": error.retryable,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
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

    @app.post("/api/profiles", tags=["system"], status_code=201)
    async def create_profile(request: Request, body: CreateProfileRequest) -> dict[str, Any]:
        return _service(request).create_profile(**body.model_dump())

    @app.post("/api/projects", tags=["projects"], status_code=201)
    async def create_project(
        request: Request,
        name: Annotated[str, Form(min_length=1, max_length=200)],
        kind: Annotated[Literal["novel", "manga"], Form()],
        source_language: Annotated[str, Form(min_length=1, max_length=40)],
        target_language: Annotated[str, Form(min_length=1, max_length=40)],
        source: Annotated[UploadFile, File(description="TXT, CBZ/ZIP, or one image")],
    ) -> dict[str, Any]:
        service = _service(request)
        payload = await source.read(service.settings.max_upload_bytes + 1)
        return service.create_project(
            name=name,
            kind=kind,
            source_language=source_language,
            target_language=target_language,
            source_name=source.filename or "source.bin",
            source_bytes=payload,
            media_type=source.content_type,
        )

    @app.get("/api/projects", tags=["projects"])
    async def list_projects(request: Request) -> list[dict[str, Any]]:
        return _service(request).list_projects()

    @app.get("/api/projects/{project_id}", tags=["projects"])
    async def get_project(request: Request, project_id: str) -> dict[str, Any]:
        return _service(request).get_project(project_id)

    @app.delete("/api/projects/{project_id}", tags=["projects"])
    async def delete_project(
        request: Request,
        project_id: str,
        confirmed: Annotated[
            bool, Query(description="Must be true after reviewing deletion impact")
        ] = False,
    ) -> dict[str, Any]:
        return _service(request).delete_project(project_id, confirmed=confirmed)

    @app.post("/api/projects/{project_id}/jobs", tags=["jobs"], status_code=202)
    async def create_job(
        request: Request, project_id: str, body: CreateJobRequest
    ) -> dict[str, Any]:
        return _service(request).create_job(project_id=project_id, **body.model_dump())

    @app.get("/api/jobs", tags=["jobs"])
    async def list_jobs(
        request: Request,
        project_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return _service(request).list_jobs(project_id=project_id, status=status)

    @app.get("/api/jobs/{job_id}", tags=["jobs"])
    async def get_job(request: Request, job_id: str) -> dict[str, Any]:
        return _service(request).get_job(job_id)

    @app.post("/api/jobs/{job_id}/pause", tags=["jobs"])
    async def pause_job(request: Request, job_id: str) -> dict[str, Any]:
        return _service(request).pause_job(job_id)

    @app.post("/api/jobs/{job_id}/resume", tags=["jobs"])
    async def resume_job(request: Request, job_id: str) -> dict[str, Any]:
        return _service(request).resume_job(job_id)

    @app.post("/api/jobs/{job_id}/cancel", tags=["jobs"])
    async def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
        return _service(request).cancel_job(job_id)

    @app.post("/api/jobs/{job_id}/retry", tags=["jobs"])
    async def retry_job(request: Request, job_id: str) -> dict[str, Any]:
        return _service(request).retry_job(job_id)

    @app.get("/api/projects/{project_id}/artifacts", tags=["artifacts"])
    async def list_artifacts(
        request: Request, project_id: str, job_id: str | None = None
    ) -> list[dict[str, Any]]:
        return _service(request).list_artifacts(project_id=project_id, job_id=job_id)

    @app.get("/api/artifacts/{artifact_id}", tags=["artifacts"])
    async def get_artifact(request: Request, artifact_id: str) -> dict[str, Any]:
        return _service(request).get_artifact(artifact_id)

    @app.get(
        "/api/artifacts/{artifact_id}/download",
        tags=["artifacts"],
        response_class=Response,
        responses={
            200: {
                "description": "Immutable Artifact payload",
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                },
            }
        },
    )
    async def download_artifact(request: Request, artifact_id: str) -> Response:
        metadata, payload = _service(request).read_artifact(artifact_id)
        return Response(
            content=payload,
            media_type=metadata["media_type"],
            headers={
                "Content-Disposition": f'attachment; filename="{metadata["filename"]}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/api/projects/{project_id}/exports", tags=["artifacts"])
    async def export_project(
        request: Request, project_id: str, format_name: str | None = None
    ) -> list[dict[str, Any]]:
        return _service(request).export_project(project_id, format_name=format_name)

    @app.get("/api/projects/{project_id}/segments", tags=["projects"])
    async def list_segments(
        request: Request, project_id: str, job_id: str | None = None
    ) -> list[dict[str, Any]]:
        return _service(request).list_segments(project_id, job_id=job_id)

    web_root = Path(str(resources.files("linguaspindle").joinpath("web")))
    web_assets = {
        "index.html": web_root.joinpath("index.html").read_bytes(),
        "app.js": web_root.joinpath("app.js").read_bytes(),
        "styles.css": web_root.joinpath("styles.css").read_bytes(),
    }

    @app.get("/", include_in_schema=False)
    async def web_index() -> Response:
        return Response(
            content=web_assets["index.html"],
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/app.js", include_in_schema=False)
    async def web_javascript() -> Response:
        return Response(
            content=web_assets["app.js"],
            media_type="text/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/styles.css", include_in_schema=False)
    async def web_styles() -> Response:
        return Response(
            content=web_assets["styles.css"],
            media_type="text/css",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/{path:path}", include_in_schema=False)
    async def web_fallback(path: str) -> Response:
        if path.startswith("api/") or path in {"health", "docs", "openapi.json"}:
            raise HTTPException(status_code=404, detail="Not found")
        return Response(
            content=web_assets["index.html"],
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    return app
