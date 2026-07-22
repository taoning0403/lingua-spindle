#!/usr/bin/env python3
"""Generate deterministic versioned core acceptance samples in a caller-owned root.

This helper intentionally generates only format samples and core/import evidence. It does not
run release gates, build packages, write an acceptance conclusion, or modify historical
versioned evidence.
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import platform
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from linguaspindle import (
    BuildResult,
    DocumentManifest,
    DocumentTranslationResult,
    MangaTranslationResult,
    MockMangaAdapter,
    MockProvider,
    SourceFormat,
    TranslationOptions,
    build_manga_output,
    inspect_document,
    inspect_manga,
    rebuild_document,
    translate_document,
    translate_manga,
)
from linguaspindle import __version__ as linguaspindle_version

FIXED_ZIP_TIME = (2020, 1, 2, 3, 4, 6)
CHECKSUMS_PATH = PurePosixPath("evidence/sample-checksums.sha256")
EXPECTED_VERSION = "0.3.0"
GENERATED_PATHS = tuple(
    PurePosixPath(value)
    for value in (
        "artifacts/samples/txt/source.txt",
        "artifacts/samples/txt/translated.txt",
        "artifacts/samples/txt/manual-rebuild.txt",
        "artifacts/samples/txt/document-manifest.json",
        "artifacts/samples/txt/segment-manifest.json",
        "artifacts/samples/txt/translation-result.json",
        "artifacts/samples/epub2/source.epub",
        "artifacts/samples/epub2/translated.epub",
        "artifacts/samples/epub2/document-manifest.json",
        "artifacts/samples/epub2/translation-result.json",
        "artifacts/samples/epub2/validation-report.json",
        "artifacts/samples/epub3/source.epub",
        "artifacts/samples/epub3/translated.epub",
        "artifacts/samples/epub3/document-manifest.json",
        "artifacts/samples/epub3/translation-result.json",
        "artifacts/samples/epub3/validation-report.json",
        "artifacts/samples/manga/cbz/source.cbz",
        "artifacts/samples/manga/cbz/translated.cbz",
        "artifacts/samples/manga/cbz/manifest.json",
        "artifacts/samples/manga/cbz/adapter-result.json",
        "artifacts/samples/manga/image/source.png",
        "artifacts/samples/manga/image/translated.png",
        "artifacts/samples/manga/image/manifest.json",
        "artifacts/samples/manga/image/adapter-result.json",
        "evidence/import-boundary.json",
        "evidence/environment.json",
        CHECKSUMS_PATH.as_posix(),
    )
)


@dataclass(frozen=True, slots=True)
class Arguments:
    repository: Path
    output: Path
    expected_commit: str


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    path: str
    size: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


def _arguments(argv: Sequence[str] | None = None) -> Arguments:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="LinguaSpindle repository root",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=f"Output root (default: <repository>/acceptance/v{EXPECTED_VERSION})",
    )
    parser.add_argument(
        "--expected-commit",
        required=True,
        help=f"Exact clean Git commit from which v{EXPECTED_VERSION} evidence must be generated",
    )
    parsed = parser.parse_args(argv)
    repository = cast(Path, parsed.repository).resolve()
    configured_output = cast(Path | None, parsed.output)
    output = (configured_output or repository / "acceptance" / f"v{EXPECTED_VERSION}").resolve()
    return Arguments(
        repository=repository,
        output=output,
        expected_commit=str(parsed.expected_commit),
    )


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _destination(output: Path, relative: PurePosixPath) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"Unsafe generated path: {relative}")
    candidate = output.joinpath(*relative.parts)
    if not candidate.resolve().is_relative_to(output.resolve()):
        raise RuntimeError(f"Generated path escapes the output root: {relative}")
    return candidate


def _validate_roots(repository: Path, output: Path) -> None:
    if not (repository / "pyproject.toml").is_file():
        raise RuntimeError(f"Not a LinguaSpindle repository: {repository}")
    acceptance_root = repository / "acceptance"
    current = (acceptance_root / f"v{EXPECTED_VERSION}").resolve()
    for candidate in acceptance_root.glob("v*"):
        historical = candidate.resolve()
        if historical == current:
            continue
        if output == historical or output.is_relative_to(historical):
            raise RuntimeError(
                f"Refusing to generate inside immutable {candidate.relative_to(repository)}"
            )
    if output.exists() and (output.is_symlink() or not output.is_dir()):
        raise RuntimeError(f"Output root must be a real directory or not exist: {output}")


def _prepare_output(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for relative in GENERATED_PATHS:
        destination = _destination(output, relative)
        if destination.is_symlink():
            raise RuntimeError(f"Refusing to replace a symlink: {destination}")
        if destination.exists():
            if not destination.is_file():
                raise RuntimeError(f"Generated destination is not a file: {destination}")
            destination.unlink()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".linguaspindle-v030-",
        suffix=".pending",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        path.chmod(0o644)
    finally:
        temporary.unlink(missing_ok=True)


def _write(output: Path, relative: str, payload: bytes) -> Path:
    path = _destination(output, PurePosixPath(relative))
    _atomic_write(path, payload)
    return path


def _write_json(output: Path, relative: str, value: object) -> Path:
    return _write(output, relative, _json_bytes(value))


def _zip_info(name: str, compression: int = zipfile.ZIP_DEFLATED) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = compression
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _zip_bytes(entries: Sequence[tuple[str, bytes, int]]) -> bytes:
    with tempfile.SpooledTemporaryFile() as buffer:
        with zipfile.ZipFile(buffer, "w", allowZip64=True) as archive:
            for name, payload, compression in entries:
                archive.writestr(_zip_info(name, compression), payload)
        buffer.seek(0)
        return buffer.read()


@contextmanager
def _deterministic_zip_writes() -> Iterator[None]:
    """Fix timestamps when a public core operation writes a ZIP member by name."""

    original = zipfile.ZipFile.writestr

    def deterministic_writestr(
        archive: zipfile.ZipFile,
        zinfo_or_arcname: zipfile.ZipInfo | str,
        data: bytes | str,
        compress_type: int | None = None,
        compresslevel: int | None = None,
    ) -> None:
        target: zipfile.ZipInfo | str = zinfo_or_arcname
        if isinstance(zinfo_or_arcname, str):
            compression = archive.compression if compress_type is None else compress_type
            target = _zip_info(zinfo_or_arcname, compression)
        original(
            archive,
            target,
            data,
            compress_type=compress_type,
            compresslevel=compresslevel,
        )

    zipfile.ZipFile.writestr = deterministic_writestr  # type: ignore[assignment,method-assign]
    try:
        yield
    finally:
        zipfile.ZipFile.writestr = original  # type: ignore[method-assign]


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    return b"\x89PNG\r\n\x1a\n" + b"".join(
        (
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(raw, level=9)),
            chunk(b"IEND", b""),
        )
    )


def _epub2_bytes() -> bytes:
    fixture_id = f"urn:uuid:linguaspindle-v{EXPECTED_VERSION.replace('.', '')}-epub2"
    container = b"""<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    package = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         unique-identifier="book-id" version="2.0">
  <metadata>
    <dc:identifier id="book-id">{fixture_id}</dc:identifier>
    <dc:title>Clockwork Harbor</dc:title>
    <dc:creator>LinguaSpindle fixture</dc:creator>
    <dc:subject>Acceptance</dc:subject>
    <dc:description>A deterministic two-chapter EPUB 2 fixture.</dc:description>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter-1" href="Text/chapter-1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter-2" href="Text/chapter-2.xhtml" media-type="application/xhtml+xml"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="cover" href="Images/cover.png" media-type="image/png"/>
    <item id="css" href="Styles/book.css" media-type="text/css"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="chapter-1"/>
    <itemref idref="chapter-2"/>
  </spine>
  <guide>
    <reference type="text" title="Start" href="Text/chapter-1.xhtml#start"/>
  </guide>
</package>
""".encode()
    chapter_1 = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
  <head><title>Chapter One</title><link rel="stylesheet" href="../Styles/book.css"/></head>
  <body><h1 id="start">Chapter One</h1>
    <p>The harbor clock struck seven.</p>
    <p><a href="chapter-2.xhtml#arrival">Continue to chapter two</a></p>
    <img src="../Images/cover.png" alt="Blue clockwork harbor"/>
  </body>
</html>
"""
    chapter_2 = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
  <head><title>Chapter Two</title><link rel="stylesheet" href="../Styles/book.css"/></head>
  <body><h1 id="arrival">Chapter Two</h1>
    <p>At dawn, the last brass ferry reached the opposite shore.</p>
    <p><a href="chapter-1.xhtml#start">Return to chapter one</a></p>
  </body>
</html>
"""
    ncx = f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="{fixture_id}"/></head>
  <docTitle><text>Clockwork Harbor</text></docTitle>
  <navMap>
    <navPoint id="one" playOrder="1"><navLabel><text>Chapter One</text></navLabel>
      <content src="Text/chapter-1.xhtml#start"/></navPoint>
    <navPoint id="two" playOrder="2"><navLabel><text>Chapter Two</text></navLabel>
      <content src="Text/chapter-2.xhtml#arrival"/></navPoint>
  </navMap>
</ncx>
""".encode()
    entries = (
        ("mimetype", b"application/epub+zip", zipfile.ZIP_STORED),
        ("META-INF/container.xml", container, zipfile.ZIP_DEFLATED),
        ("OEBPS/content.opf", package, zipfile.ZIP_DEFLATED),
        ("OEBPS/Text/chapter-1.xhtml", chapter_1, zipfile.ZIP_DEFLATED),
        ("OEBPS/Text/chapter-2.xhtml", chapter_2, zipfile.ZIP_DEFLATED),
        ("OEBPS/toc.ncx", ncx, zipfile.ZIP_DEFLATED),
        ("OEBPS/Images/cover.png", _png(48, 64, (37, 92, 143)), zipfile.ZIP_STORED),
        (
            "OEBPS/Styles/book.css",
            b"body { color: #17243a; } img { max-width: 100%; }\n",
            zipfile.ZIP_DEFLATED,
        ),
    )
    return _zip_bytes(entries)


def _manga_cbz_bytes() -> bytes:
    entries = (
        ("pages/001.png", _png(40, 56, (209, 82, 69)), zipfile.ZIP_DEFLATED),
        ("pages/002.png", _png(40, 56, (69, 132, 209)), zipfile.ZIP_DEFLATED),
        ("pages/010.png", _png(40, 56, (94, 168, 116)), zipfile.ZIP_DEFLATED),
    )
    return _zip_bytes(entries)


def _generate_txt(output: Path) -> None:
    source_bytes = (
        b"Chapter One\r\n\r\n"
        b"The night ferry left the clockwork harbor.\r\n\r\n"
        b"Chapter Two\r\n\r\n"
        b"At dawn, its bell answered from the far shore.\r\n"
    )
    source = _write(output, "artifacts/samples/txt/source.txt", source_bytes)
    options = TranslationOptions(
        source_language="en",
        target_language="zh-CN",
        max_retries=0,
        retry_backoff_seconds=0,
    )
    manifest = inspect_document(source, options=options)
    original_sha256 = _sha256_file(source)
    translated_path = _destination(output, PurePosixPath("artifacts/samples/txt/translated.txt"))
    translated = translate_document(source, translated_path, MockProvider(), options)
    if translated.manifest != manifest:
        raise RuntimeError("TXT inspection changed between inspect and translate calls")
    if len(manifest.segments) < 2:
        raise RuntimeError("TXT fixture did not produce representative Segments")

    manual_segment = manifest.segments[1]
    manual_text = "人工校订：发条港的夜航船已经离岸。"
    manual_path = _destination(output, PurePosixPath("artifacts/samples/txt/manual-rebuild.txt"))
    manual_build = rebuild_document(
        source,
        manifest,
        {manual_segment.segment_id: manual_text},
        manual_path,
        target_language=options.target_language,
    )
    if _sha256_file(source) != original_sha256:
        raise RuntimeError("TXT source changed during public core operations")

    _write_json(
        output,
        "artifacts/samples/txt/document-manifest.json",
        manifest.to_dict(),
    )
    _write_json(
        output,
        "artifacts/samples/txt/segment-manifest.json",
        {
            "schema_version": "acceptance-segment-manifest.v1",
            "source_sha256": manifest.source_sha256,
            "source_format": manifest.source_format.value,
            "segment_count": len(manifest.segments),
            "segments": [segment.to_dict() for segment in manifest.segments],
            "manual_rebuild": {
                "segment_id": manual_segment.segment_id,
                "translated_text": manual_text,
                "build": manual_build.to_dict(),
            },
        },
    )
    _write_json(
        output,
        "artifacts/samples/txt/translation-result.json",
        translated.to_dict(),
    )


def _epub_validation(
    source: Path,
    source_manifest: DocumentManifest,
    translated_path: Path,
    translation_result: DocumentTranslationResult,
    source_sha256: str,
) -> dict[str, object]:
    output_manifest = inspect_document(translated_path)
    checks = {
        "source_immutable": _sha256_file(source) == source_sha256,
        "format_preserved": output_manifest.source_format is source_manifest.source_format,
        "output_hash_matches_build": (
            _sha256_file(translated_path) == translation_result.build.output_sha256
        ),
        "all_segments_translated": (
            translation_result.build.translated_count == len(source_manifest.segments)
            and translation_result.build.preserved_count == 0
        ),
        "public_reinspection_succeeded": len(output_manifest.segments) > 0,
    }
    if not all(checks.values()):
        raise RuntimeError(f"EPUB public validation failed: {checks}")
    return {
        "schema_version": "acceptance-epub-validation.v1",
        "scope": "linguaspindle-public-core-reinspection",
        "source_format": source_manifest.source_format.value,
        "source_sha256": source_manifest.source_sha256,
        "output_sha256": translation_result.build.output_sha256,
        "output_manifest": {
            "source_format": output_manifest.source_format.value,
            "source_sha256": output_manifest.source_sha256,
            "source_size": output_manifest.source_size,
            "segment_count": len(output_manifest.segments),
            "metadata": output_manifest.metadata,
        },
        "checks": checks,
        "build": translation_result.build.to_dict(),
    }


def _generate_epub(
    output: Path,
    *,
    label: str,
    source_bytes: bytes,
    expected_format: SourceFormat,
    target_language: str,
) -> None:
    base = f"artifacts/samples/{label}"
    source = _write(output, f"{base}/source.epub", source_bytes)
    options = TranslationOptions(
        source_language="auto",
        target_language=target_language,
        max_retries=0,
        retry_backoff_seconds=0,
    )
    manifest = inspect_document(source, options=options)
    if manifest.source_format is not expected_format:
        raise RuntimeError(
            f"{label} fixture inspected as {manifest.source_format.value}, "
            f"expected {expected_format.value}"
        )
    source_sha256 = _sha256_file(source)
    translated_path = _destination(output, PurePosixPath(f"{base}/translated.epub"))
    translated = translate_document(source, translated_path, MockProvider(), options)
    validation = _epub_validation(
        source,
        manifest,
        translated_path,
        translated,
        source_sha256,
    )
    _write_json(output, f"{base}/document-manifest.json", manifest.to_dict())
    _write_json(output, f"{base}/translation-result.json", translated.to_dict())
    _write_json(output, f"{base}/validation-report.json", validation)


def _manga_result_payload(
    result: MangaTranslationResult,
    build: BuildResult,
    translated_path: Path,
) -> dict[str, object]:
    output_sha256 = _sha256_file(translated_path)
    if output_sha256 != build.output_sha256:
        raise RuntimeError("Manga output checksum does not match its public BuildResult")
    serialized: dict[str, object] = dict(result.to_dict(include_binary=False))
    serialized["pages"] = [
        {
            key: value
            for key, value in page.to_dict(include_binary=False).items()
            if key != "image_base64"
        }
        for page in result.pages
    ]
    binary_evidence = [
        {
            "page_id": page.page_id,
            "image_in_json": False,
            "image_size": len(page.image) if page.image is not None else None,
            "image_sha256": _sha256_bytes(page.image) if page.image is not None else None,
        }
        for page in result.pages
    ]
    output_manifest = inspect_manga(translated_path)
    return {
        "schema_version": "acceptance-manga-adapter-result.v1",
        "binary_policy": "omitted-from-json; sizes-and-sha256-recorded",
        "adapter_manifest": MockMangaAdapter().manifest.public(),
        "translation": serialized,
        "binary_evidence": binary_evidence,
        "build": build.to_dict(),
        "output": {
            "sha256": output_sha256,
            "size": translated_path.stat().st_size,
            "source_format": output_manifest.source_format.value,
            "page_count": len(output_manifest.pages),
            "page_sha256": [page.source_sha256 for page in output_manifest.pages],
        },
    }


def _generate_manga_sample(
    output: Path,
    *,
    label: str,
    filename: str,
    source_bytes: bytes,
) -> None:
    base = f"artifacts/samples/manga/{label}"
    source = _write(output, f"{base}/{filename}", source_bytes)
    manifest = inspect_manga(source)
    adapter = MockMangaAdapter()
    translated = translate_manga(
        source,
        adapter,
        TranslationOptions(
            source_language="ja",
            target_language="en",
            max_retries=0,
            retry_backoff_seconds=0,
        ),
        manifest=manifest,
    )
    output_filename = (
        "translated.cbz" if manifest.source_format is SourceFormat.CBZ else "translated.png"
    )
    translated_path = _destination(output, PurePosixPath(f"{base}/{output_filename}"))
    with _deterministic_zip_writes():
        build = build_manga_output(translated, translated_path)
    if _sha256_file(source) != manifest.source_sha256:
        raise RuntimeError("Manga source changed during public core operations")
    _write_json(output, f"{base}/manifest.json", manifest.to_dict())
    _write_json(
        output,
        f"{base}/adapter-result.json",
        _manga_result_payload(translated, build, translated_path),
    )


def _import_boundary_evidence(repository: Path) -> dict[str, object]:
    probe = r"""
import json
import pathlib
import sys

workspace = pathlib.Path(sys.argv[1])
data_root = pathlib.Path(sys.argv[2])
before = sorted(path.relative_to(workspace).as_posix() for path in workspace.rglob("*"))
import linguaspindle
after = sorted(path.relative_to(workspace).as_posix() for path in workspace.rglob("*"))
forbidden = (
    "linguaspindle.application",
    "linguaspindle.config",
    "linguaspindle.database",
    "linguaspindle.interfaces",
    "linguaspindle.models",
    "linguaspindle.orchestration.engine",
    "linguaspindle.runtime",
    "linguaspindle.storage",
    "fastapi",
    "httpx",
    "platformdirs",
    "pydantic",
    "sqlalchemy",
    "starlette",
    "typer",
    "uvicorn",
)
loaded = sorted(
    name
    for name in sys.modules
    if any(name == root or name.startswith(root + ".") for root in forbidden)
)
print(json.dumps({
    "package_version": linguaspindle.__version__,
    "linguaspindle_modules_loaded": sorted(
        name for name in sys.modules if name == "linguaspindle" or name.startswith("linguaspindle.")
    ),
    "optional_modules_loaded": loaded,
    "data_root_created": data_root.exists(),
    "filesystem_entries_created": sorted(set(after) - set(before)),
}, sort_keys=True))
"""
    with tempfile.TemporaryDirectory(prefix="linguaspindle-v030-import-") as temporary:
        workspace = Path(temporary)
        home = workspace / "home"
        home.mkdir()
        data_root = workspace / "must-not-be-created"
        environment = os.environ.copy()
        for key in tuple(environment):
            if key.startswith("LINGUASPINDLE_"):
                environment.pop(key)
        environment.update(
            {
                "HOME": str(home),
                "LINGUASPINDLE_DATA_ROOT": str(data_root),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(repository / "src"),
            }
        )
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-c", probe, str(workspace), str(data_root)],
            cwd=workspace,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            "Core import-boundary probe failed: "
            f"exit={completed.returncode}, stderr={completed.stderr.strip()!r}"
        )
    try:
        observed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Core import-boundary probe returned invalid JSON") from exc
    if not isinstance(observed, dict):
        raise RuntimeError("Core import-boundary probe returned a non-object")
    optional_loaded = observed.get("optional_modules_loaded")
    created = observed.get("filesystem_entries_created")
    if optional_loaded or created or observed.get("data_root_created"):
        raise RuntimeError(f"Core import boundary was violated: {observed}")
    return {
        "schema_version": "acceptance-import-boundary.v1",
        "probe": "fresh-process top-level import from repository src",
        "exit_code": completed.returncode,
        "stderr": completed.stderr,
        "observed": observed,
    }


def _git_commit(repository: Path) -> str | None:
    completed = subprocess.run(  # noqa: S603
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _validate_release_source(repository: Path, expected_commit: str) -> None:
    if linguaspindle_version != EXPECTED_VERSION:
        raise RuntimeError(
            f"Acceptance requires LinguaSpindle {EXPECTED_VERSION}, got {linguaspindle_version}"
        )
    actual_commit = _git_commit(repository)
    if actual_commit != expected_commit:
        raise RuntimeError(
            f"Acceptance source commit mismatch: expected {expected_commit}, got {actual_commit}"
        )
    completed = subprocess.run(  # noqa: S603
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],  # noqa: S607
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("Could not verify the acceptance source working tree")
    if completed.stdout.strip():
        raise RuntimeError("Acceptance source working tree must be clean")


def _environment_metadata(repository: Path) -> dict[str, object]:
    return {
        "schema_version": "acceptance-environment.v1",
        "artifact_scope": f"v{EXPECTED_VERSION} core samples only",
        "linguaspindle_version": linguaspindle_version,
        "git_commit": _git_commit(repository),
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "network_used": False,
        "provider": "mock",
        "manga_adapter": "mock-manga",
        "external_model_execution": False,
    }


def _write_checksums(output: Path) -> None:
    lines: list[str] = []
    for relative in sorted(path for path in GENERATED_PATHS if path != CHECKSUMS_PATH):
        path = _destination(output, relative)
        if not path.is_file():
            raise RuntimeError(f"Expected generated file is missing: {relative}")
        lines.append(f"{_sha256_file(path)}  {relative.as_posix()}")
    _atomic_write(_destination(output, CHECKSUMS_PATH), ("\n".join(lines) + "\n").encode())


def _inventory(output: Path) -> tuple[GeneratedFile, ...]:
    files: list[GeneratedFile] = []
    for relative in sorted(GENERATED_PATHS):
        path = _destination(output, relative)
        if not path.is_file():
            raise RuntimeError(f"Expected generated file is missing: {relative}")
        files.append(
            GeneratedFile(
                path=relative.as_posix(),
                size=path.stat().st_size,
                sha256=_sha256_file(path),
            )
        )
    return tuple(files)


def generate(
    repository: Path,
    output: Path,
    *,
    expected_commit: str,
) -> tuple[GeneratedFile, ...]:
    """Generate the fixed versioned core sample set without touching historical evidence."""

    repository = repository.resolve()
    output = output.resolve()
    _validate_roots(repository, output)
    _validate_release_source(repository, expected_commit)
    _prepare_output(output)

    epub3_source = (
        repository
        / "acceptance"
        / "v0.2.0"
        / "artifacts"
        / "samples"
        / "epub"
        / "source-multichapter.epub"
    )
    if not epub3_source.is_file():
        raise RuntimeError(f"Tracked v0.2.0 EPUB 3 sample is missing: {epub3_source}")

    _generate_txt(output)
    _generate_epub(
        output,
        label="epub2",
        source_bytes=_epub2_bytes(),
        expected_format=SourceFormat.EPUB2,
        target_language="zh-CN",
    )
    _generate_epub(
        output,
        label="epub3",
        source_bytes=epub3_source.read_bytes(),
        expected_format=SourceFormat.EPUB3,
        target_language="en",
    )
    _generate_manga_sample(
        output,
        label="cbz",
        filename="source.cbz",
        source_bytes=_manga_cbz_bytes(),
    )
    _generate_manga_sample(
        output,
        label="image",
        filename="source.png",
        source_bytes=_png(48, 64, (121, 84, 156)),
    )
    _write_json(output, "evidence/import-boundary.json", _import_boundary_evidence(repository))
    _write_json(output, "evidence/environment.json", _environment_metadata(repository))
    _write_checksums(output)
    return _inventory(output)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments(argv)
    inventory = generate(
        arguments.repository,
        arguments.output,
        expected_commit=arguments.expected_commit,
    )
    print(
        json.dumps(
            {
                "output": str(arguments.output),
                "generated_file_count": len(inventory),
                "files": [item.to_dict() for item in inventory],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
