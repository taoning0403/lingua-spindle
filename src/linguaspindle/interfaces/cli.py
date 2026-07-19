"""Typer CLI over the shared application service."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer
import uvicorn

from ..application import ApplicationService
from ..config import ConfigurationError, Settings
from ..errors import LinguaError
from ..orchestration.engine import JobRunner
from .api import create_app

app = typer.Typer(
    name="linguaspindle",
    no_args_is_help=True,
    help="Persistent translation orchestration for novels and manga.",
)
projects_app = typer.Typer(no_args_is_help=True, help="Manage translation Projects.")
jobs_app = typer.Typer(no_args_is_help=True, help="Inspect and control persistent Jobs.")
artifacts_app = typer.Typer(no_args_is_help=True, help="Inspect immutable Artifacts.")
adapters_app = typer.Typer(no_args_is_help=True, help="Inspect external Adapters.")
app.add_typer(projects_app, name="projects")
app.add_typer(jobs_app, name="jobs")
app.add_typer(artifacts_app, name="artifacts")
app.add_typer(adapters_app, name="adapters")


def _print(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _settings(data_dir: Path | None) -> Settings:
    try:
        return Settings.from_env(data_dir)
    except ConfigurationError as error:
        _print(
            {
                "error": {
                    "code": "CONFIGURATION_ERROR",
                    "message": str(error),
                    "details": {},
                }
            }
        )
        raise typer.Exit(2) from error


@contextmanager
def _service(data_dir: Path | None) -> Iterator[ApplicationService]:
    service = ApplicationService(_settings(data_dir))
    try:
        yield service
    except LinguaError as error:
        _print(
            service.redact_for_persistence(
                {
                    "error": {
                        "code": error.code,
                        "message": error.message,
                        "details": error.details or {},
                    }
                }
            )
        )
        raise typer.Exit(2) from error
    finally:
        service.close()


DataDir = Annotated[
    Path | None,
    typer.Option("--data-dir", envvar="LINGUASPINDLE_DATA_DIR", help="Mutable data root."),
]


@app.command()
def serve(
    data_dir: DataDir = None,
    host: Annotated[
        str | None, typer.Option(help="Bind address; loopback is the safe default.")
    ] = None,
    port: Annotated[int | None, typer.Option(min=1, max=65535)] = None,
) -> None:
    """Start the Web GUI, HTTP API, and background runner."""
    settings = _settings(data_dir)
    if host:
        settings.host = host
    if port:
        settings.port = port
    if settings.host not in {"127.0.0.1", "localhost", "::1"}:
        typer.secho(
            "Warning: this instance has no built-in login. "
            "Protect remote access with an outer perimeter.",
            fg=typer.colors.YELLOW,
            err=True,
        )
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


@app.command()
def doctor(data_dir: DataDir = None) -> None:
    """Check storage, database, port, Docker, Providers, and Adapters."""
    with _service(data_dir) as service:
        report = service.doctor()
        _print(report)
        if not report["ok"]:
            raise typer.Exit(1)


@projects_app.command("list")
def projects_list(data_dir: DataDir = None) -> None:
    with _service(data_dir) as service:
        _print(service.list_projects())


@projects_app.command("create")
def projects_create(
    name: Annotated[str, typer.Option(prompt=True)],
    kind: Annotated[str, typer.Option(help="novel or manga")],
    source_language: Annotated[str, typer.Option("--source-language", "-s")],
    target_language: Annotated[str, typer.Option("--target-language", "-t")],
    source: Annotated[Path, typer.Option(exists=True, readable=True)],
    data_dir: DataDir = None,
) -> None:
    with _service(data_dir) as service:
        _print(
            service.create_project_from_path(
                name=name,
                kind=kind,
                source_language=source_language,
                target_language=target_language,
                source_path=source,
            )
        )


@projects_app.command("show")
def projects_show(project_id: str, data_dir: DataDir = None) -> None:
    with _service(data_dir) as service:
        _print(service.get_project(project_id))


@projects_app.command("delete")
def projects_delete(
    project_id: str,
    yes: Annotated[
        bool, typer.Option("--yes", help="Confirm deletion and all listed effects")
    ] = False,
    data_dir: DataDir = None,
) -> None:
    with _service(data_dir) as service:
        impact = service.project_deletion_impact(project_id)
        _print({"project_id": project_id, "impact": impact})
        confirmed = yes or typer.confirm("Delete this Project and its Jobs and Artifacts?")
        _print(service.delete_project(project_id, confirmed=confirmed))


@app.command()
def run(
    project_id: str,
    provider: Annotated[str | None, typer.Option()] = None,
    adapter: Annotated[str | None, typer.Option()] = None,
    profile_id: Annotated[str | None, typer.Option()] = None,
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = True,
    timeout: Annotated[float, typer.Option(min=1)] = 300.0,
    data_dir: DataDir = None,
) -> None:
    """Create a Job and optionally execute it in this process."""
    with _service(data_dir) as service:
        job = service.create_job(
            project_id=project_id,
            provider_id=provider,
            adapter_id=adapter,
            profile_id=profile_id,
        )
        if wait:
            runner = JobRunner(service)
            runner.run_once()
            job = runner.run_until_terminal(job["id"], timeout=timeout)
        _print(job)


@jobs_app.command("list")
def jobs_list(
    project_id: Annotated[str | None, typer.Option()] = None,
    status: Annotated[str | None, typer.Option()] = None,
    data_dir: DataDir = None,
) -> None:
    with _service(data_dir) as service:
        _print(service.list_jobs(project_id=project_id, status=status))


@jobs_app.command("show")
def jobs_show(job_id: str, data_dir: DataDir = None) -> None:
    with _service(data_dir) as service:
        _print(service.get_job(job_id))


@jobs_app.command("pause")
def jobs_pause(job_id: str, data_dir: DataDir = None) -> None:
    with _service(data_dir) as service:
        _print(service.pause_job(job_id))


@jobs_app.command("resume")
def jobs_resume(job_id: str, data_dir: DataDir = None) -> None:
    with _service(data_dir) as service:
        _print(service.resume_job(job_id))


@jobs_app.command("cancel")
def jobs_cancel(job_id: str, data_dir: DataDir = None) -> None:
    with _service(data_dir) as service:
        _print(service.cancel_job(job_id))


@jobs_app.command("retry")
def jobs_retry(
    job_id: str,
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = False,
    data_dir: DataDir = None,
) -> None:
    with _service(data_dir) as service:
        job = service.retry_job(job_id)
        if wait:
            runner = JobRunner(service)
            runner.run_once()
            job = runner.run_until_terminal(job_id)
        _print(job)


@artifacts_app.command("list")
def artifacts_list(
    project_id: str,
    job_id: Annotated[str | None, typer.Option()] = None,
    data_dir: DataDir = None,
) -> None:
    with _service(data_dir) as service:
        _print(service.list_artifacts(project_id=project_id, job_id=job_id))


@app.command()
def export(
    project_id: str,
    format_name: Annotated[str | None, typer.Option("--format")] = None,
    data_dir: DataDir = None,
) -> None:
    with _service(data_dir) as service:
        _print(service.export_project(project_id, format_name=format_name))


@adapters_app.command("list")
def adapters_list(data_dir: DataDir = None) -> None:
    with _service(data_dir) as service:
        _print(service.adapter_statuses())


@adapters_app.command("doctor")
def adapters_doctor(data_dir: DataDir = None) -> None:
    with _service(data_dir) as service:
        statuses = service.adapter_statuses()
        _print(statuses)
        if not any(item["health"]["available"] for item in statuses):
            raise typer.Exit(1)


if __name__ == "__main__":
    app()
