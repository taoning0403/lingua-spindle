"""Typer commands for the optional headless CLI.

Only Typer and the side-effect-free public core are imported at module load.
Persistent runtime and HTTP server dependencies are resolved inside commands.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, NoReturn, TypeVar

import typer

from .. import (
    MockMangaAdapter,
    MockProvider,
    TranslationOptions,
    __version__,
    build_manga_output,
    inspect_document,
    inspect_manga,
    translate_document,
    translate_manga,
)
from ..errors import ErrorCode, LinguaError

T = TypeVar("T")

app = typer.Typer(
    name="linguaspindle",
    no_args_is_help=True,
    help="Headless translation core with optional local persistence.",
)
documents_app = typer.Typer(no_args_is_help=True, help="Inspect and translate TXT or EPUB.")
manga_app = typer.Typer(no_args_is_help=True, help="Inspect and translate images or CBZ/ZIP.")
projects_app = typer.Typer(no_args_is_help=True, help="Manage persistent translation Projects.")
jobs_app = typer.Typer(no_args_is_help=True, help="Inspect and control persistent Jobs.")
artifacts_app = typer.Typer(no_args_is_help=True, help="Inspect immutable Artifacts.")
adapters_app = typer.Typer(no_args_is_help=True, help="Inspect external Adapters.")
app.add_typer(documents_app, name="document")
app.add_typer(manga_app, name="manga")
app.add_typer(projects_app, name="projects")
app.add_typer(jobs_app, name="jobs")
app.add_typer(artifacts_app, name="artifacts")
app.add_typer(adapters_app, name="adapters")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the LinguaSpindle version and exit.",
        ),
    ] = False,
) -> None:
    """Headless translation core with optional local persistence."""


@app.command("version")
def version_command() -> None:
    """Show the LinguaSpindle version."""

    typer.echo(__version__)


def _print(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _dependency_error(extra: str, error: ModuleNotFoundError) -> NoReturn:
    missing = error.name or "optional dependency"
    _print(
        {
            "error": {
                "code": ErrorCode.DEPENDENCY_MISSING,
                "message": (
                    f"This command requires the optional [{extra}] extra; "
                    f"install it with: pip install 'linguaspindle[{extra}]'"
                ),
                "details": {"missing_module": missing, "extra": extra},
                "retryable": False,
            }
        }
    )
    raise typer.Exit(2) from error


@lru_cache(maxsize=1)
def _runtime_components() -> SimpleNamespace:
    try:
        runtime = importlib.import_module("linguaspindle.runtime")
        config = importlib.import_module("linguaspindle.config")
    except ModuleNotFoundError as error:
        _dependency_error("runtime", error)
    return SimpleNamespace(
        LocalRuntime=runtime.LocalRuntime,
        JobRunner=runtime.JobRunner,
        Settings=runtime.Settings,
        ConfigurationError=config.ConfigurationError,
    )


@lru_cache(maxsize=1)
def _server_components() -> SimpleNamespace:
    try:
        uvicorn = importlib.import_module("uvicorn")
        api = importlib.import_module("linguaspindle.interfaces.api")
    except ModuleNotFoundError as error:
        _dependency_error("server", error)
    return SimpleNamespace(run=uvicorn.run, create_app=api.create_app)


def _settings(data_dir: Path | None) -> Any:
    runtime = _runtime_components()
    try:
        return runtime.Settings.from_env(data_dir)
    except runtime.ConfigurationError as error:
        _print(
            {
                "error": {
                    "code": ErrorCode.CONFIGURATION,
                    "message": str(error),
                    "details": {},
                    "retryable": False,
                }
            }
        )
        raise typer.Exit(2) from error


@contextmanager
def _service(data_dir: Path | None) -> Iterator[Any]:
    runtime = _runtime_components()
    service = runtime.LocalRuntime(_settings(data_dir))
    try:
        yield service
    except LinguaError as error:
        _print({"error": service.redact_for_persistence(error.to_dict())})
        raise typer.Exit(2) from error
    finally:
        service.close()


def _core_call(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except LinguaError as error:
        _print({"error": error.to_dict()})
        raise typer.Exit(2) from error
    except ValueError as error:
        normalized = LinguaError(ErrorCode.CONFIGURATION, str(error))
        _print({"error": normalized.to_dict()})
        raise typer.Exit(2) from error


DataDir = Annotated[
    Path | None,
    typer.Option("--data-dir", envvar="LINGUASPINDLE_DATA_DIR", help="Mutable data root."),
]


@documents_app.command("inspect")
def document_inspect(
    source: Annotated[Path, typer.Argument(exists=True, readable=True)],
    format_hint: Annotated[
        str | None, typer.Option("--format", help="txt, epub, epub2, or epub3")
    ] = None,
    source_language: Annotated[str, typer.Option("--source-language", "-s")] = "auto",
    target_language: Annotated[str, typer.Option("--target-language", "-t")] = "en",
    max_segment_chars: Annotated[int, typer.Option(min=1)] = 1_800,
) -> None:
    """Inspect a TXT or EPUB source and print its versioned manifest."""

    options = TranslationOptions(
        source_language=source_language,
        target_language=target_language,
        max_segment_chars=max_segment_chars,
    )
    manifest = _core_call(
        lambda: inspect_document(source, format_hint=format_hint, options=options)
    )
    _print(manifest.to_dict())


@documents_app.command("translate")
def document_translate(
    source: Annotated[Path, typer.Argument(exists=True, readable=True)],
    output: Annotated[Path, typer.Option("--output", "-o")],
    source_language: Annotated[str, typer.Option("--source-language", "-s")] = "auto",
    target_language: Annotated[str, typer.Option("--target-language", "-t")] = "en",
    format_hint: Annotated[
        str | None, typer.Option("--format", help="txt, epub, epub2, or epub3")
    ] = None,
    max_segment_chars: Annotated[int, typer.Option(min=1)] = 1_800,
    concurrency: Annotated[int, typer.Option(min=1, max=32)] = 1,
    max_retries: Annotated[int, typer.Option(min=0, max=20)] = 2,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Translate TXT or EPUB through the deterministic offline Mock Provider."""

    options = TranslationOptions(
        source_language=source_language,
        target_language=target_language,
        max_segment_chars=max_segment_chars,
        concurrency=concurrency,
        max_retries=max_retries,
    )
    result = _core_call(
        lambda: translate_document(
            source,
            output,
            MockProvider(),
            options,
            format_hint=format_hint,
            overwrite=overwrite,
        )
    )
    _print(result.to_dict())


@manga_app.command("inspect")
def manga_inspect(
    source: Annotated[Path, typer.Argument(exists=True, readable=True)],
    maximum_bytes: Annotated[int, typer.Option("--maximum-bytes", min=1)] = 100 * 1024 * 1024,
) -> None:
    """Inspect a single image or CBZ/ZIP and print its page manifest."""

    manifest = _core_call(lambda: inspect_manga(source, maximum_bytes=maximum_bytes))
    _print(manifest.to_dict())


@manga_app.command("translate")
def manga_translate(
    source: Annotated[Path, typer.Argument(exists=True, readable=True)],
    output: Annotated[Path, typer.Option("--output", "-o")],
    source_language: Annotated[str, typer.Option("--source-language", "-s")] = "auto",
    target_language: Annotated[str, typer.Option("--target-language", "-t")] = "en",
    max_retries: Annotated[int, typer.Option(min=0, max=20)] = 2,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Translate image/CBZ pages through the deterministic offline Mock Adapter."""

    options = TranslationOptions(
        source_language=source_language,
        target_language=target_language,
        max_retries=max_retries,
    )

    def operation() -> dict[str, object]:
        if source.resolve() == output.resolve():
            raise LinguaError(
                ErrorCode.INVALID_STATE,
                "Manga output must not overwrite the immutable source",
            )
        translated = translate_manga(source, MockMangaAdapter(), options)
        built = build_manga_output(translated, output, overwrite=overwrite)
        return {
            "translation": translated.to_dict(include_binary=False),
            "build": built.to_dict(),
        }

    _print(_core_call(operation))


@app.command("validate")
def validate_output(
    source: Annotated[Path, typer.Argument(exists=True, readable=True)],
    kind: Annotated[str, typer.Option(help="auto, document, or manga")] = "auto",
    target_language: Annotated[str, typer.Option("--target-language", "-t")] = "en",
) -> None:
    """Validate a generated TXT/EPUB/image/CBZ output by reopening and inspecting it."""

    selected = kind.strip().casefold()
    if selected not in {"auto", "document", "manga"}:
        error = LinguaError(
            ErrorCode.CONFIGURATION,
            "--kind must be auto, document, or manga",
        )
        _print({"error": error.to_dict()})
        raise typer.Exit(2)
    manga_suffixes = {".cbz", ".zip", ".png", ".jpg", ".jpeg", ".webp"}
    use_manga = selected == "manga" or (
        selected == "auto" and source.suffix.casefold() in manga_suffixes
    )
    if use_manga:
        manga_manifest = _core_call(lambda: inspect_manga(source))
        _print({"valid": True, "kind": "manga", "manifest": manga_manifest.to_dict()})
        return
    options = TranslationOptions(target_language=target_language)
    document_manifest = _core_call(lambda: inspect_document(source, options=options))
    _print({"valid": True, "kind": "document", "manifest": document_manifest.to_dict()})


@app.command()
def serve(
    data_dir: DataDir = None,
    host: Annotated[
        str | None, typer.Option(help="Bind address; loopback is the safe default.")
    ] = None,
    port: Annotated[int | None, typer.Option(min=1, max=65535)] = None,
) -> None:
    """Start the optional headless HTTP API and persistent runner."""

    settings = _settings(data_dir)
    server = _server_components()
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
    server.run(
        server.create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


@app.command()
def doctor(data_dir: DataDir = None) -> None:
    """Check optional runtime storage, database, Providers, and Adapters."""

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
    pipeline: Annotated[str | None, typer.Option(help="Explicit Pipeline preset key.")] = None,
    provider: Annotated[str | None, typer.Option()] = None,
    adapter: Annotated[str | None, typer.Option()] = None,
    profile_id: Annotated[str | None, typer.Option()] = None,
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = True,
    timeout: Annotated[float, typer.Option(min=1)] = 300.0,
    data_dir: DataDir = None,
) -> None:
    """Create a persistent Job and optionally execute it in this process."""

    runtime = _runtime_components()
    with _service(data_dir) as service:
        job = service.create_job(
            project_id=project_id,
            pipeline_key=pipeline,
            provider_id=provider,
            adapter_id=adapter,
            profile_id=profile_id,
        )
        if wait:
            runner = runtime.JobRunner(service)
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
    runtime = _runtime_components()
    with _service(data_dir) as service:
        job = service.retry_job(job_id)
        if wait:
            runner = runtime.JobRunner(service)
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
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Copy one matching Artifact to this path."),
    ] = None,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Replace an existing output file.")
    ] = False,
    data_dir: DataDir = None,
) -> None:
    with _service(data_dir) as service:
        artifacts = service.export_project(project_id, format_name=format_name)
        if output is None:
            _print(artifacts)
            return
        if len(artifacts) != 1:
            raise LinguaError(
                code=ErrorCode.INVALID_STATE,
                message="--output requires exactly one matching export; specify --format",
            )
        destination = output.expanduser()
        if destination.is_dir():
            destination = destination / artifacts[0]["filename"]
        if destination.exists() and not overwrite:
            raise LinguaError(
                code=ErrorCode.INVALID_STATE,
                message="Output path already exists; pass --overwrite to replace it",
                details={"output": str(destination)},
            )
        artifact, copied_path = service.copy_artifact(artifacts[0]["id"], destination)
        _print({"artifact": artifact, "output": str(copied_path)})


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


__all__ = ["app"]
