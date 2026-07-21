from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from io import BytesIO
from pathlib import Path

import linguaspindle
from linguaspindle import (
    AdapterHealth,
    AdapterManifest,
    MangaAdapterResult,
    MangaTranslationAdapter,
    TranslationOptions,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
    TranslationStatus,
    inspect_document,
    inspect_manga,
    translate_manga,
    translate_segments,
)

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
    "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
)


def test_import_is_side_effect_free_and_keeps_optional_layers_unloaded(tmp_path: Path) -> None:
    sentinel = tmp_path / "must-not-be-created"
    script = textwrap.dedent(
        """
        import json
        import os
        import sqlite3
        import sys
        import threading
        from pathlib import Path

        environment_reads = []
        database_calls = []
        thread_starts = []
        environment_type = type(os.environ)
        original_get = environment_type.get
        original_getitem = environment_type.__getitem__
        original_contains = environment_type.__contains__

        def tracked_get(self, key, default=None):
            if str(key).startswith("LINGUASPINDLE_"):
                environment_reads.append(str(key))
            return original_get(self, key, default)

        def tracked_getitem(self, key):
            if str(key).startswith("LINGUASPINDLE_"):
                environment_reads.append(str(key))
            return original_getitem(self, key)

        def tracked_contains(self, key):
            if str(key).startswith("LINGUASPINDLE_"):
                environment_reads.append(str(key))
            return original_contains(self, key)

        def denied_connect(*args, **kwargs):
            database_calls.append(str(args[0]) if args else "unknown")
            raise AssertionError("import attempted to open SQLite")

        def denied_start(self):
            thread_starts.append(self.name)
            raise AssertionError("import attempted to start a thread")

        environment_type.get = tracked_get
        environment_type.__getitem__ = tracked_getitem
        environment_type.__contains__ = tracked_contains
        sqlite3.connect = denied_connect
        threading.Thread.start = denied_start

        before_files = sorted(path.name for path in Path.cwd().iterdir())
        before_threads = sorted(thread.name for thread in threading.enumerate())
        import linguaspindle
        after_files = sorted(path.name for path in Path.cwd().iterdir())
        after_threads = sorted(thread.name for thread in threading.enumerate())

        forbidden_prefixes = (
            "linguaspindle.runtime",
            "linguaspindle.interfaces",
            "linguaspindle.adapters.http_manga",
            "linguaspindle.providers.openai_compatible",
            "fastapi",
            "httpx",
            "platformdirs",
            "pydantic",
            "sqlalchemy",
            "typer",
            "uvicorn",
        )
        forbidden_modules = sorted(
            name for name in sys.modules if name.startswith(forbidden_prefixes)
        )
        result = {
            "database_calls": database_calls,
            "environment_reads": environment_reads,
            "files_changed": before_files != after_files,
            "forbidden_modules": forbidden_modules,
            "sentinel_exists": Path(os.environ["CORE_IMPORT_SENTINEL"]).exists(),
            "thread_starts": thread_starts,
            "threads_changed": before_threads != after_threads,
            "version": linguaspindle.__version__,
        }
        print(json.dumps(result, sort_keys=True))
        """
    )
    environment = os.environ.copy()
    environment["CORE_IMPORT_SENTINEL"] = str(sentinel)
    environment["LINGUASPINDLE_DATA_DIR"] = str(sentinel)

    completed = subprocess.run(  # noqa: S603 - fixed interpreter and in-test source only
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    observed = json.loads(completed.stdout)
    assert observed["database_calls"] == []
    assert observed["environment_reads"] == []
    assert observed["files_changed"] is False
    assert observed["forbidden_modules"] == []
    assert observed["sentinel_exists"] is False
    assert observed["thread_starts"] == []
    assert observed["threads_changed"] is False


def test_root_package_exposes_the_headless_core_contract() -> None:
    expected = {
        "AdapterHealth",
        "AdapterManifest",
        "ArchiveLimits",
        "CancellationToken",
        "DocumentManifest",
        "MangaTranslationAdapter",
        "MockMangaAdapter",
        "MockProvider",
        "Segment",
        "TranslationOptions",
        "TranslationProvider",
        "build_manga_output",
        "build_translated_epub",
        "extract_segments",
        "inspect_document",
        "inspect_epub",
        "inspect_manga",
        "rebuild_document",
        "translate_document",
        "translate_manga",
        "translate_segments",
    }

    assert expected <= set(linguaspindle.__all__)
    assert all(hasattr(linguaspindle, name) for name in expected)


def test_caller_defined_provider_implements_public_protocol() -> None:
    class UpperProvider:
        id = "caller-upper"

        def translate(self, request: TranslationRequest) -> TranslationResult:
            return TranslationResult(request.text.upper(), model="caller-model")

    provider = UpperProvider()
    manifest = inspect_document(b"one\n\ntwo\n", filename="caller.txt")

    result = translate_segments(
        manifest,
        provider,
        TranslationOptions(target_language="fr", max_retries=0),
    )

    assert isinstance(provider, TranslationProvider)
    assert [record.translated_text for record in result.records] == ["ONE", "TWO"]
    assert all(record.provider_id == provider.id for record in result.records)


def test_caller_defined_manga_adapter_implements_public_protocol() -> None:
    class CallerAdapter:
        manifest = AdapterManifest(
            id="caller-manga",
            display_name="Caller Manga",
            adapter_version="1",
            upstream_version="caller",
            invocation_type="in_process",
            capabilities=("manga_full_pipeline",),
            input_formats=("png",),
            output_formats=("png",),
            languages=("*",),
            requires_gpu=False,
            supports_cancel=False,
            supports_progress=False,
            health_check="call",
            configuration_help="none",
            upstream_url="",
            upstream_license="Apache-2.0",
            modified=False,
        )

        def health(self) -> AdapterHealth:
            return AdapterHealth(True, "ready")

        def translate_image(
            self,
            *,
            image: bytes,
            filename: str,
            source_language: str,
            target_language: str,
        ) -> MangaAdapterResult:
            return MangaAdapterResult(
                image=image,
                media_type="image/png",
                raw_metadata={"filename": filename, "target_language": target_language},
            )

    adapter = CallerAdapter()
    manifest = inspect_manga(BytesIO(PNG_1X1), filename="page.png")
    result = translate_manga(
        BytesIO(PNG_1X1),
        adapter,
        TranslationOptions(target_language="ja", max_retries=0),
        manifest=manifest,
    )

    assert isinstance(adapter, MangaTranslationAdapter)
    assert result.adapter_id == adapter.manifest.id
    assert result.pages[0].status is TranslationStatus.SUCCEEDED
    assert result.pages[0].image == PNG_1X1
