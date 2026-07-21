#!/usr/bin/env python3
"""Verify every LinguaSpindle v0.3 wheel extra in a fresh virtual environment.

The verifier intentionally performs installation work only when invoked.  Its
smoke checks are offline: configured network clients are constructed but never
contacted, and every mutable sample or database lives below a disposable
temporary directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
import time
import tomllib
import venv
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "linguaspindle-extra-verification.v1"
EXPECTED_VERSION = "0.3.0"
EXTRAS = ("core", "openai", "manga", "runtime", "cli", "server", "all")
_SECRET_NAME = re.compile(
    r"(?:TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE)", re.IGNORECASE
)
_URL_CREDENTIALS = re.compile(r"(?P<scheme>https?://)[^/@\s]+@", re.IGNORECASE)
_URL_SECRET_QUERY = re.compile(
    r"(?i)([?&](?:access_token|api_key|apikey|auth|credential|password|secret|token)=)[^&#\s]+"
)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)((?:api[_-]?key|token|secret|password|credential)\s*[=:]\s*)[^\s,;]+"
)


CORE_SMOKE = r"""
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

optional = ("fastapi", "httpx", "platformdirs", "pydantic", "sqlalchemy", "typer", "uvicorn")
missing = {name: importlib.util.find_spec(name) is None for name in optional}
assert all(missing.values()), missing

import linguaspindle
from linguaspindle import (
    MockMangaAdapter,
    MockProvider,
    TranslationOptions,
    build_manga_output,
    inspect_document,
    inspect_manga,
    translate_document,
    translate_manga,
)

assert not any(name in sys.modules for name in optional)
try:
    import linguaspindle.interfaces.api  # noqa: F401
except ModuleNotFoundError as error:
    assert "linguaspindle[server]" in str(error), str(error)
else:
    raise AssertionError("Core-only install unexpectedly imported optional server support")
work = Path(sys.argv[1])
epub_source = Path(sys.argv[2])
options = TranslationOptions(
    source_language="en",
    target_language="fr",
    max_retries=0,
    retry_backoff_seconds=0,
)

txt_source = work / "source.txt"
txt_source.write_text("First paragraph.\n\nSecond paragraph.\n", encoding="utf-8")
txt_manifest = inspect_document(txt_source, options=options)
assert txt_manifest.source_format.value == "txt"
assert len(txt_manifest.segments) == 2
txt_output = work / "translated.txt"
txt_result = translate_document(txt_source, txt_output, MockProvider(), options)
assert txt_result.build.translated_count == 2
assert "[fr]" in txt_output.read_text(encoding="utf-8")

epub_manifest = inspect_document(epub_source, options=options)
assert epub_manifest.source_format.value == "epub3", epub_manifest.source_format
assert epub_manifest.segments
epub_output = work / "translated.epub"
epub_result = translate_document(epub_source, epub_output, MockProvider(), options)
assert epub_result.build.translated_count > 0
assert inspect_document(epub_output, options=options).source_format.value == "epub3"

png = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
    "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
)
png_source = work / "page.png"
png_source.write_bytes(png)
png_manifest = inspect_manga(png_source)
assert png_manifest.source_format.value == "image"
png_result = translate_manga(png_source, MockMangaAdapter(), options)
png_output = work / "translated.png"
build_manga_output(png_result, png_output)
assert png_output.read_bytes() == png

cbz_source = work / "source.cbz"
with zipfile.ZipFile(cbz_source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("pages/01.png", png)
    archive.writestr("pages/02.png", png)
cbz_manifest = inspect_manga(cbz_source)
assert cbz_manifest.source_format.value == "cbz"
assert len(cbz_manifest.pages) == 2
cbz_result = translate_manga(cbz_source, MockMangaAdapter(), options)
cbz_output = work / "translated.cbz"
build_manga_output(cbz_result, cbz_output)
assert len(inspect_manga(cbz_output).pages) == 2

assert not any(name in sys.modules for name in optional)
print(json.dumps({
    "version": linguaspindle.__version__,
    "optional_modules_absent": missing,
    "txt_segments": len(txt_manifest.segments),
    "epub_format": epub_manifest.source_format.value,
    "epub_segments": len(epub_manifest.segments),
    "png_pages": len(png_manifest.pages),
    "cbz_pages": len(cbz_manifest.pages),
    "provider": "mock",
    "manga_adapter": "mock-manga",
}))
"""


OPENAI_SMOKE = r"""
import json

from linguaspindle.errors import ErrorCode, LinguaError
from linguaspindle.providers.base import TranslationRequest
from linguaspindle.providers.openai_compatible import (
    OpenAICompatibleProvider,
    OpenAIProviderConfig,
)

config = OpenAIProviderConfig(
    base_url="https://example.invalid/v1",
    model="offline-model",
    timeout_seconds=1.0,
)
provider = OpenAICompatibleProvider(config)
assert not provider.configured()
status = provider.public_status()
assert status["secret_source"] == "caller_runtime"
assert "api_key" not in json.dumps(status)
try:
    provider.translate(
        TranslationRequest(
            text="Offline only",
            source_language="en",
            target_language="fr",
        )
    )
except LinguaError as error:
    assert error.code is ErrorCode.CONFIGURATION
else:
    raise AssertionError("An unconfigured Provider must fail before network I/O")

resolver_config = OpenAIProviderConfig(
    base_url="https://example.invalid/v1",
    model="offline-model",
    api_key_resolver=lambda: "offline-placeholder",
)
resolver_provider = OpenAICompatibleProvider(resolver_config)
assert resolver_provider.configured()
assert "offline-placeholder" not in repr(resolver_config)
print(json.dumps({
    "provider": resolver_provider.id,
    "explicit_config": True,
    "unconfigured_fails_before_network": True,
    "secret_repr_safe": True,
}))
"""


MANGA_SMOKE = r"""
import json

from linguaspindle.adapters.manga_image_translator import (
    MangaImageTranslatorConfig,
    MangaImageTranslatorHttpAdapter,
)
from linguaspindle.errors import ErrorCode, LinguaError

config = MangaImageTranslatorConfig(
    base_url=None,
    timeout_seconds=1.0,
    request_config={"renderer": {"quality": 90}},
)
adapter = MangaImageTranslatorHttpAdapter(config)
health = adapter.health()
assert not health.available
assert health.details["required_setting"] == "LINGUASPINDLE_MIT_BASE_URL"
try:
    adapter.translate_image(
        image=b"not-sent",
        filename="page.png",
        source_language="ja",
        target_language="en",
    )
except LinguaError as error:
    assert error.code is ErrorCode.ADAPTER_UNAVAILABLE
else:
    raise AssertionError("An unconfigured Adapter must fail before network I/O")
print(json.dumps({
    "adapter": adapter.manifest.id,
    "explicit_config": True,
    "health_without_network": True,
    "unconfigured_fails_before_network": True,
}))
"""


RUNTIME_SMOKE = r"""
import json
import sqlite3
import sys
import threading
from pathlib import Path

from linguaspindle.runtime import LocalRuntime, Settings

root = Path(sys.argv[1]) / "runtime-data"
before = {(thread.ident, thread.name) for thread in threading.enumerate()}
runtime = LocalRuntime(Settings(data_dir=root))
try:
    after = {(thread.ident, thread.name) for thread in threading.enumerate()}
    assert after == before, {"before": sorted(before), "after": sorted(after)}
    health = runtime.health()
    assert health["status"] == "ok"
    assert health["database"] == "ok"
finally:
    runtime.close()

connection = sqlite3.connect(root / "database" / "linguaspindle.sqlite3")
try:
    versions = [row[0] for row in connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    )]
    columns = [row[1] for row in connection.execute("PRAGMA table_info(translation_segments)")]
finally:
    connection.close()
assert {1, 2, 3}.issubset(versions), versions
assert "segment_key" in columns
print(json.dumps({
    "migration_versions": versions,
    "stable_segment_key_column": True,
    "background_threads_started": 0,
    "database_created": True,
}))
"""


SERVER_SMOKE = r"""
import asyncio
import inspect
import json
import sys
from pathlib import Path

from linguaspindle.config import Settings
from linguaspindle.interfaces.api import create_app

app = create_app(Settings(data_dir=Path(sys.argv[1]) / "server-data"), start_worker=False)
schema = app.openapi()
paths = set(schema["paths"])
required = {
    "/health",
    "/api/projects/{project_id}/segments",
    "/api/projects/{project_id}/segments/translate",
    "/api/projects/{project_id}/rebuild",
}
assert required.issubset(paths), required - paths
route_paths = {str(getattr(route, "path", "")) for route in app.routes}
assert not any(
    path.startswith(("/assets", "/static", "/gui", "/web")) for path in route_paths
)
assert not any("{path:path}" in path for path in route_paths)
assert not any(type(route).__name__ == "Mount" for route in app.routes)
root_route = next(route for route in app.routes if getattr(route, "path", None) == "/")
value = root_route.endpoint()
root = asyncio.run(value) if inspect.isawaitable(value) else value
assert root["mode"] == "headless"
assert root["openapi"] == "/openapi.json"
assert "html" not in json.dumps(root).lower()
print(json.dumps({
    "openapi_version": schema["openapi"],
    "document_routes_present": True,
    "route_count": len(route_paths),
    "root_mode": root["mode"],
    "gui_routes_present": False,
    "fallback_route_present": False,
    "test_client_dependency_required": False,
}))
"""


ALL_SMOKE = r"""
import asyncio
import inspect
import json
import sqlite3
import sys
import threading
from pathlib import Path

import linguaspindle
from linguaspindle import (
    MockMangaAdapter,
    MockProvider,
    TranslationOptions,
    inspect_document,
    inspect_manga,
    translate_document,
    translate_manga,
)
from linguaspindle.adapters.manga_image_translator import (
    MangaImageTranslatorConfig,
    MangaImageTranslatorHttpAdapter,
)
from linguaspindle.interfaces.api import create_app
from linguaspindle.interfaces.cli import app as cli_app
from linguaspindle.providers.openai_compatible import (
    OpenAICompatibleProvider,
    OpenAIProviderConfig,
)
from linguaspindle.runtime import LocalRuntime, Settings

work = Path(sys.argv[1])
epub_source = Path(sys.argv[2])
options = TranslationOptions(target_language="fr", max_retries=0, retry_backoff_seconds=0)
txt = work / "all-source.txt"
txt.write_text("All-extra smoke.\n", encoding="utf-8")
txt_output = work / "all-output.txt"
document = translate_document(txt, txt_output, MockProvider(), options)
assert document.build.translated_count == 1
assert inspect_document(epub_source, options=options).source_format.value == "epub3"

png = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
    "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
)
png_source = work / "all-page.png"
png_source.write_bytes(png)
manga = translate_manga(png_source, MockMangaAdapter(), options)
assert len(manga.pages) == 1
assert inspect_manga(png_source).source_format.value == "image"

openai = OpenAICompatibleProvider(OpenAIProviderConfig(base_url="https://example.invalid/v1"))
assert not openai.configured()
http_manga = MangaImageTranslatorHttpAdapter(MangaImageTranslatorConfig())
assert not http_manga.health().available
assert callable(cli_app)

before = {(thread.ident, thread.name) for thread in threading.enumerate()}
settings = Settings(data_dir=work / "all-runtime")
runtime = LocalRuntime(settings)
try:
    assert {(thread.ident, thread.name) for thread in threading.enumerate()} == before
finally:
    runtime.close()
connection = sqlite3.connect(settings.database_path)
try:
    migrations = [row[0] for row in connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    )]
finally:
    connection.close()
assert {1, 2, 3}.issubset(migrations)

app = create_app(Settings(data_dir=work / "all-server"), start_worker=False)
schema = app.openapi()
root_route = next(route for route in app.routes if getattr(route, "path", None) == "/")
value = root_route.endpoint()
root = asyncio.run(value) if inspect.isawaitable(value) else value
assert root["mode"] == "headless"
assert not any("{path:path}" in str(getattr(route, "path", "")) for route in app.routes)
print(json.dumps({
    "version": linguaspindle.__version__,
    "core": True,
    "openai": True,
    "manga": True,
    "runtime": True,
    "cli": True,
    "server": True,
    "migration_versions": migrations,
    "openapi_paths": len(schema["paths"]),
}))
"""


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install and smoke-test every LinguaSpindle wheel extra in isolation."
    )
    parser.add_argument("--wheel", type=Path, required=True, help="Exact wheel under test.")
    parser.add_argument(
        "--repository",
        type=Path,
        required=True,
        help="Repository containing the tracked v0.2 EPUB3 acceptance sample.",
    )
    parser.add_argument("--output", type=Path, required=True, help="Versioned JSON report path.")
    parser.add_argument(
        "--expected-commit",
        required=True,
        help="Exact clean Git commit from which the tested wheel was built",
    )
    parser.add_argument(
        "--constraint", type=Path, help="Optional pip constraints file used in every venv."
    )
    return parser.parse_args(argv)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wheel_identity(path: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            metadata_files = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_files) != 1:
                raise SystemExit("Wheel must contain exactly one dist-info/METADATA file")
            metadata = archive.read(metadata_files[0]).decode("utf-8")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"Wheel metadata could not be read: {type(exc).__name__}") from exc
    fields: dict[str, str] = {}
    for line in metadata.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            fields.setdefault(key, value)
        if not line:
            break
    return fields.get("Name", ""), fields.get("Version", "")


def _repository_release_state(repository: Path) -> tuple[str, str]:
    pyproject = repository / "pyproject.toml"
    try:
        project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
        project_version = str(project["version"])
    except (KeyError, OSError, tomllib.TOMLDecodeError, TypeError) as exc:
        raise SystemExit("Repository project version could not be read") from exc
    commit = subprocess.run(  # noqa: S603
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    status = subprocess.run(  # noqa: S603
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],  # noqa: S607
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if commit.returncode != 0 or status.returncode != 0:
        raise SystemExit("Repository Git state could not be verified")
    if status.stdout.strip():
        raise SystemExit("Repository working tree must be clean before Wheel verification")
    return commit.stdout.strip(), project_version


def _secret_values() -> tuple[str, ...]:
    values = {
        value
        for name, value in os.environ.items()
        if value and len(value) >= 8 and _SECRET_NAME.search(name)
    }
    return tuple(sorted(values, key=len, reverse=True))


def _sanitize(text: str, *, paths: dict[str, Path], secrets: Sequence[str]) -> str:
    sanitized = text
    replacements = sorted(
        ((str(path), marker) for marker, path in paths.items()),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for value, marker in replacements:
        if value:
            sanitized = sanitized.replace(value, marker)
    home = str(Path.home())
    if home:
        sanitized = sanitized.replace(home, "<home>")
    for secret in secrets:
        sanitized = sanitized.replace(secret, "<redacted>")
    sanitized = _URL_CREDENTIALS.sub(r"\g<scheme><redacted>@", sanitized)
    sanitized = _URL_SECRET_QUERY.sub(r"\1<redacted>", sanitized)
    sanitized = _BEARER.sub(r"\1<redacted>", sanitized)
    sanitized = _SECRET_ASSIGNMENT.sub(r"\1<redacted>", sanitized)
    return sanitized


def _subprocess_environment(*, smoke: bool) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONUTF8"] = "1"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    environment["PIP_NO_INPUT"] = "1"
    if smoke:
        for name in tuple(environment):
            if name.startswith("LINGUASPINDLE_") or _SECRET_NAME.search(name):
                environment.pop(name, None)
    return environment


def _python_path(root: Path) -> Path:
    if os.name == "nt":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _run_command(
    command: Sequence[str],
    *,
    name: str,
    display: str,
    cwd: Path,
    environment: dict[str, str],
    paths: dict[str, Path],
    secrets: Sequence[str],
    timeout: float,
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str] | None]:
    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603 - command is assembled from fixed executables
            list(command),
            cwd=cwd,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        elapsed = round(time.monotonic() - started, 3)
        diagnostic = _sanitize(
            (_text(error.stderr) or _text(error.stdout))[-4_000:],
            paths=paths,
            secrets=secrets,
        )
        return (
            {
                "name": name,
                "command": display,
                "status": "Fail",
                "returncode": None,
                "duration_seconds": elapsed,
                "reason": "timeout",
                **({"diagnostic": diagnostic} if diagnostic else {}),
            },
            None,
        )
    except OSError as error:
        elapsed = round(time.monotonic() - started, 3)
        return (
            {
                "name": name,
                "command": display,
                "status": "Fail",
                "returncode": None,
                "duration_seconds": elapsed,
                "reason": type(error).__name__,
                "diagnostic": _sanitize(str(error), paths=paths, secrets=secrets),
            },
            None,
        )
    elapsed = round(time.monotonic() - started, 3)
    outcome: dict[str, Any] = {
        "name": name,
        "command": display,
        "status": "Pass" if completed.returncode == 0 else "Fail",
        "returncode": completed.returncode,
        "duration_seconds": elapsed,
    }
    if completed.returncode != 0:
        diagnostic = _sanitize(
            (completed.stderr or completed.stdout)[-4_000:], paths=paths, secrets=secrets
        )
        if diagnostic:
            outcome["diagnostic"] = diagnostic
    return outcome, completed


def _json_stdout(completed: subprocess.CompletedProcess[str] | None) -> dict[str, Any]:
    if completed is None or completed.returncode != 0:
        raise ValueError("Command did not complete successfully")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("Smoke output must be a JSON object")
    return value


def _assertion_outcome(name: str, operation: Any) -> dict[str, Any]:
    started = time.monotonic()
    try:
        operation()
    except Exception as error:
        return {
            "name": name,
            "command": "in-process report assertion",
            "status": "Fail",
            "returncode": None,
            "duration_seconds": round(time.monotonic() - started, 3),
            "reason": f"{type(error).__name__}: {error}",
        }
    return {
        "name": name,
        "command": "in-process report assertion",
        "status": "Pass",
        "returncode": 0,
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def _install_target(wheel: Path, extra: str) -> str:
    if extra == "core":
        return str(wheel)
    return f"linguaspindle[{extra}] @ {wheel.as_uri()}"


def _smoke_script(extra: str) -> str:
    return {
        "core": CORE_SMOKE,
        "openai": OPENAI_SMOKE,
        "manga": MANGA_SMOKE,
        "runtime": RUNTIME_SMOKE,
        "server": SERVER_SMOKE,
        "all": ALL_SMOKE,
    }[extra]


def _verify_cli(
    python: Path,
    work: Path,
    *,
    paths: dict[str, Path],
    secrets: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    environment = _subprocess_environment(smoke=True)
    source = work / "cli-source.txt"
    output = work / "cli-translated.txt"
    source.write_text("CLI first paragraph.\n\nCLI second paragraph.\n", encoding="utf-8")
    specifications = (
        (
            "cli-version",
            [str(python), "-I", "-m", "linguaspindle.interfaces.cli", "--version"],
            "python -I -m linguaspindle.interfaces.cli --version",
        ),
        (
            "cli-document-inspect",
            [
                str(python),
                "-I",
                "-m",
                "linguaspindle.interfaces.cli",
                "document",
                "inspect",
                str(source),
                "--target-language",
                "fr",
            ],
            "linguaspindle document inspect <sample> --target-language fr",
        ),
        (
            "cli-document-translate",
            [
                str(python),
                "-I",
                "-m",
                "linguaspindle.interfaces.cli",
                "document",
                "translate",
                str(source),
                "--output",
                str(output),
                "--target-language",
                "fr",
            ],
            "linguaspindle document translate <sample> --output <output> --target-language fr",
        ),
        (
            "cli-validate",
            [
                str(python),
                "-I",
                "-m",
                "linguaspindle.interfaces.cli",
                "validate",
                str(output),
            ],
            "linguaspindle validate <output>",
        ),
    )
    outcomes: list[dict[str, Any]] = []
    completed_commands: list[subprocess.CompletedProcess[str] | None] = []
    for name, command, display in specifications:
        outcome, completed = _run_command(
            command,
            name=name,
            display=display,
            cwd=work,
            environment=environment,
            paths=paths,
            secrets=secrets,
            timeout=120,
        )
        outcomes.append(outcome)
        completed_commands.append(completed)

    smoke: dict[str, Any] = {}

    def validate_outputs() -> None:
        version, inspected, translated, validated = completed_commands
        if any(item is None or item.returncode != 0 for item in completed_commands):
            raise ValueError("One or more CLI commands failed")
        assert version is not None
        version_text = version.stdout.strip()
        inspect_payload = _json_stdout(inspected)
        translate_payload = _json_stdout(translated)
        validate_payload = _json_stdout(validated)
        if inspect_payload.get("schema_version") != "document-manifest.v1":
            raise ValueError("CLI inspect returned an unexpected schema")
        segments = inspect_payload.get("segments")
        if not isinstance(segments, list) or len(segments) != 2:
            raise ValueError("CLI inspect did not return both source Segments")
        build = translate_payload.get("build")
        if not isinstance(build, dict) or int(build.get("translated_count", 0)) != 2:
            raise ValueError("CLI translate did not build both translated Segments")
        if validate_payload.get("valid") is not True or validate_payload.get("kind") != "document":
            raise ValueError("CLI validate did not accept the translated document")
        if not output.is_file() or "[fr]" not in output.read_text(encoding="utf-8"):
            raise ValueError("CLI translated output is missing")
        smoke.update(
            {
                "version": version_text,
                "inspect_schema": inspect_payload["schema_version"],
                "inspect_segments": len(segments),
                "translated_segments": int(build["translated_count"]),
                "validate_kind": validate_payload["kind"],
                "runtime_dependency_required": False,
            }
        )

    outcomes.append(_assertion_outcome("cli-offline-workflow", validate_outputs))
    return outcomes, smoke


def _verify_extra(
    extra: str,
    *,
    wheel: Path,
    repository: Path,
    constraint: Path | None,
    secrets: Sequence[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "extra": extra,
        "status": "Fail",
        "commands": [],
        "dependencies": [],
        "smoke": {},
    }
    with tempfile.TemporaryDirectory(prefix=f"linguaspindle-v030-{extra}-") as temporary:
        root = Path(temporary)
        environment_root = root / "venv"
        work = root / "work"
        work.mkdir()
        paths = {
            "<temporary>": root,
            "<repository>": repository,
            "<wheel>": wheel,
        }
        if constraint is not None:
            paths["<constraint>"] = constraint

        create_started = time.monotonic()
        try:
            # POSIX installations such as uv-managed macOS Python builds must
            # preserve the interpreter symlink; copying the signed executable
            # can make ensurepip abort before an extra is tested.
            venv.EnvBuilder(
                with_pip=True,
                clear=True,
                symlinks=os.name != "nt",
            ).create(environment_root)
        except Exception as error:
            result["commands"].append(
                {
                    "name": "create-venv",
                    "command": "python -m venv <temporary>/venv",
                    "status": "Fail",
                    "returncode": None,
                    "duration_seconds": round(time.monotonic() - create_started, 3),
                    "reason": type(error).__name__,
                    "diagnostic": _sanitize(str(error), paths=paths, secrets=secrets),
                }
            )
            return result
        result["commands"].append(
            {
                "name": "create-venv",
                "command": "python -m venv <temporary>/venv",
                "status": "Pass",
                "returncode": 0,
                "duration_seconds": round(time.monotonic() - create_started, 3),
            }
        )
        python = _python_path(environment_root)
        install = [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
        ]
        display = f"pip install linguaspindle{'' if extra == 'core' else f'[{extra}]'} @ <wheel>"
        if constraint is not None:
            install.extend(("--constraint", str(constraint)))
            display += " --constraint <constraint>"
        install.append(_install_target(wheel, extra))
        install_outcome, installed = _run_command(
            install,
            name="install-wheel-extra",
            display=display,
            cwd=work,
            environment=_subprocess_environment(smoke=False),
            paths=paths,
            secrets=secrets,
            timeout=600,
        )
        result["commands"].append(install_outcome)
        if installed is None or installed.returncode != 0:
            return result

        check_outcome, _ = _run_command(
            [str(python), "-m", "pip", "check"],
            name="pip-check",
            display="pip check",
            cwd=work,
            environment=_subprocess_environment(smoke=True),
            paths=paths,
            secrets=secrets,
            timeout=120,
        )
        result["commands"].append(check_outcome)
        list_outcome, listed = _run_command(
            [str(python), "-m", "pip", "list", "--format=json"],
            name="dependency-inventory",
            display="pip list --format=json",
            cwd=work,
            environment=_subprocess_environment(smoke=True),
            paths=paths,
            secrets=secrets,
            timeout=120,
        )
        result["commands"].append(list_outcome)
        try:
            packages = json.loads(listed.stdout) if listed is not None else []
            if not isinstance(packages, list):
                raise ValueError("pip list did not return an array")
            result["dependencies"] = sorted(
                [
                    {"name": str(package["name"]), "version": str(package["version"])}
                    for package in packages
                    if isinstance(package, dict) and "name" in package and "version" in package
                ],
                key=lambda package: package["name"].casefold(),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            result["commands"].append(
                {
                    "name": "parse-dependency-inventory",
                    "command": "parse pip list JSON",
                    "status": "Fail",
                    "returncode": None,
                    "duration_seconds": 0.0,
                    "reason": f"{type(error).__name__}: {error}",
                }
            )

        if extra == "cli":
            outcomes, smoke = _verify_cli(python, work, paths=paths, secrets=secrets)
            result["commands"].extend(outcomes)
            result["smoke"] = smoke
        else:
            arguments = [str(work)]
            if extra in {"core", "all"}:
                arguments.append(
                    str(
                        repository
                        / "acceptance"
                        / "v0.2.0"
                        / "artifacts"
                        / "samples"
                        / "epub"
                        / "source-multichapter.epub"
                    )
                )
            smoke_outcome, completed = _run_command(
                [str(python), "-I", "-c", _smoke_script(extra), *arguments],
                name=f"{extra}-offline-smoke",
                display=f"isolated {extra} offline smoke",
                cwd=work,
                environment=_subprocess_environment(smoke=True),
                paths=paths,
                secrets=secrets,
                timeout=240,
            )
            result["commands"].append(smoke_outcome)
            try:
                result["smoke"] = _json_stdout(completed)
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                if completed is not None and completed.returncode == 0:
                    result["commands"].append(
                        {
                            "name": "parse-smoke-result",
                            "command": "parse controlled smoke JSON",
                            "status": "Fail",
                            "returncode": None,
                            "duration_seconds": 0.0,
                            "reason": f"{type(error).__name__}: {error}",
                        }
                    )

        result["status"] = (
            "Pass"
            if result["commands"]
            and all(command.get("status") == "Pass" for command in result["commands"])
            else "Fail"
        )
    return result


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        temporary_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    wheel = arguments.wheel.resolve()
    repository = arguments.repository.resolve()
    output = arguments.output.resolve()
    constraint = arguments.constraint.resolve() if arguments.constraint else None
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise SystemExit(f"--wheel must name an existing .whl file: {wheel}")
    if not repository.is_dir():
        raise SystemExit(f"--repository must name an existing directory: {repository}")
    epub_sample = (
        repository
        / "acceptance"
        / "v0.2.0"
        / "artifacts"
        / "samples"
        / "epub"
        / "source-multichapter.epub"
    )
    if not epub_sample.is_file():
        raise SystemExit(f"Tracked EPUB3 acceptance sample is missing: {epub_sample}")
    if constraint is not None and not constraint.is_file():
        raise SystemExit(f"--constraint must name an existing file: {constraint}")
    wheel_name, wheel_version = _wheel_identity(wheel)
    repository_commit, repository_version = _repository_release_state(repository)
    if wheel_name != "linguaspindle" or wheel_version != EXPECTED_VERSION:
        raise SystemExit(
            f"Wheel must be linguaspindle {EXPECTED_VERSION}, got {wheel_name} {wheel_version}"
        )
    if repository_version != EXPECTED_VERSION:
        raise SystemExit(
            f"Repository must declare version {EXPECTED_VERSION}, got {repository_version}"
        )
    if repository_commit != arguments.expected_commit:
        raise SystemExit(
            "Repository commit does not match --expected-commit: "
            f"{repository_commit} != {arguments.expected_commit}"
        )

    started = datetime.now(UTC)
    secrets = _secret_values()
    extra_reports = [
        _verify_extra(
            extra,
            wheel=wheel,
            repository=repository,
            constraint=constraint,
            secrets=secrets,
        )
        for extra in EXTRAS
    ]
    finished = datetime.now(UTC)
    status = "Pass" if all(item["status"] == "Pass" for item in extra_reports) else "Fail"
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "status": status,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 3),
        "host": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "wheel": {
            "filename": wheel.name,
            "name": wheel_name,
            "version": wheel_version,
            "size": wheel.stat().st_size,
            "sha256": _sha256(wheel),
        },
        "repository": {
            "commit": repository_commit,
            "version": repository_version,
            "working_tree_clean": True,
        },
        "repository_sample": {
            "path": "acceptance/v0.2.0/artifacts/samples/epub/source-multichapter.epub",
            "sha256": _sha256(epub_sample),
        },
        "constraint": (
            {"filename": constraint.name, "sha256": _sha256(constraint)}
            if constraint is not None
            else None
        ),
        "extras": extra_reports,
    }
    _write_report(output, report)
    print(f"{status}: wrote {output}")
    return 0 if status == "Pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
