#!/usr/bin/env python3
"""Generate deterministic v0.2.0 acceptance samples and resource evidence.

The committed samples are created through ApplicationService, JobRunner, the offline Mock
Provider, and the Mock Manga Adapter.  The larger measurement EPUB exists only in a temporary
data root; the repository receives its checksum and measured metadata, not the fixture itself.
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
import time
import uuid
import zipfile
import zlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import linguaspindle.application as application_module
from linguaspindle.application import ApplicationService
from linguaspindle.config import Settings
from linguaspindle.epub import inspect_epub
from linguaspindle.models import TranslationProfile
from linguaspindle.orchestration.engine import JobRunner

FIXED_ZIP_TIME = (2020, 1, 2, 3, 4, 6)
FIXED_RUNTIME_TIME = datetime(2020, 1, 2, 3, 4, 6, tzinfo=UTC)
ID_NAMESPACE = uuid.UUID("0664512c-e327-55dd-965e-97b689cab78a")
LARGE_RESOURCE_BYTES = 24 * 1024 * 1024
LARGE_CHAPTER_COUNT = 260
LARGE_AUXILIARY_RESOURCE_COUNT = 240


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="LinguaSpindle repository root",
    )
    parser.add_argument("--measure-worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-data-root", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _utf8(value: str) -> bytes:
    return value.encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.pending")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _active_provider_secrets(repository: Path) -> tuple[bytes, ...]:
    """Read active values without ever returning them as printable text."""

    values: list[str] = []
    environment_value = os.environ.get("LINGUASPINDLE_OPENAI_API_KEY", "").strip()
    if environment_value:
        values.append(environment_value)
    dotenv = repository / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            candidate = line.strip()
            if not candidate or candidate.startswith("#") or "=" not in candidate:
                continue
            name, value = candidate.split("=", 1)
            if name.strip() != "LINGUASPINDLE_OPENAI_API_KEY":
                continue
            cleaned = value.strip()
            if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
                cleaned = cleaned[1:-1]
            if cleaned:
                values.append(cleaned)
    return tuple(dict.fromkeys(value.encode() for value in values if value))


def _file_contains(path: Path, needle: bytes) -> bool:
    if not needle:
        return False
    overlap = b""
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            candidate = overlap + chunk
            if needle in candidate:
                return True
            overlap_size = len(needle) - 1
            overlap = candidate[-overlap_size:] if overlap_size else b""
    return False


def _assert_no_active_provider_secrets(repository: Path) -> None:
    secrets = _active_provider_secrets(repository)
    if not secrets:
        return
    acceptance_root = repository / "acceptance" / "v0.2.0"
    for path in sorted(acceptance_root.rglob("*")):
        if path.is_file() and any(_file_contains(path, secret) for secret in secrets):
            relative = path.relative_to(repository).as_posix()
            raise RuntimeError(
                f"Active Provider key found in generated acceptance file: {relative}"
            )


def _zip_info(name: str, compression: int = zipfile.ZIP_DEFLATED) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = compression
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _write_zip_member(
    archive: zipfile.ZipFile,
    name: str,
    payload: bytes,
    compression: int = zipfile.ZIP_DEFLATED,
) -> None:
    archive.writestr(_zip_info(name, compression), payload)


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


def _create_sample_epub(path: Path) -> None:
    entries: list[tuple[str, bytes, int]] = [
        ("mimetype", b"application/epub+zip", zipfile.ZIP_STORED),
        (
            "META-INF/container.xml",
            b"""<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/content.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
            zipfile.ZIP_DEFLATED,
        ),
        (
            "EPUB/content.opf",
            _utf8("""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0"
  unique-identifier="book-id" xml:lang="zh-CN">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">urn:uuid:4ee4af71-c1a8-5dcc-a1cb-86b48fc96397</dc:identifier>
    <dc:title>星港纪事</dc:title>
    <dc:creator>陶宁</dc:creator>
    <dc:language>zh-CN</dc:language>
    <dc:subject>科幻</dc:subject>
    <dc:description>一段跨越两章的短途航行。</dc:description>
    <meta property="dcterms:modified">2020-01-02T03:04:06Z</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="cover-page" href="cover.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter-1" href="chapter-1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter-2" href="chapter-2.xhtml" media-type="application/xhtml+xml"/>
    <item id="notes" href="notes.xhtml" media-type="application/xhtml+xml"/>
    <item id="style" href="styles/book.css" media-type="text/css"/>
    <item id="cover" href="images/cover.png" media-type="image/png"
      properties="cover-image"/>
    <item id="diagram" href="images/diagram.png" media-type="image/png"/>
    <item id="paper" href="images/paper.png" media-type="image/png"/>
  </manifest>
  <spine>
    <itemref idref="cover-page" linear="no"/>
    <itemref idref="chapter-1"/>
    <itemref idref="chapter-2"/>
    <itemref idref="notes"/>
  </spine>
</package>
"""),
            zipfile.ZIP_DEFLATED,
        ),
        (
            "EPUB/nav.xhtml",
            _utf8("""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
  xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN" xml:lang="zh-CN">
  <head><title>目录</title><link rel="stylesheet" href="styles/book.css"/></head>
  <body><nav epub:type="toc" id="toc"><h1>目录</h1><ol>
    <li><a href="chapter-1.xhtml#departure">第一章 启航</a></li>
    <li><a href="chapter-2.xhtml#arrival">第二章 抵达</a></li>
    <li><a href="notes.xhtml#notes">注释</a></li>
  </ol></nav></body>
</html>
"""),
            zipfile.ZIP_DEFLATED,
        ),
        (
            "EPUB/cover.xhtml",
            _utf8("""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-CN" xml:lang="zh-CN">
  <head><title>封面</title></head>
  <body><section><h1>星港纪事</h1>
    <img src="images/cover.png" alt="蓝色星港封面" title="封面图"/>
  </section></body>
</html>
"""),
            zipfile.ZIP_DEFLATED,
        ),
        (
            "EPUB/chapter-1.xhtml",
            _utf8("""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-CN" xml:lang="zh-CN">
  <head><title>第一章 启航</title><link rel="stylesheet" href="styles/book.css"/></head>
  <body><article id="departure"><h1>第一章 启航</h1>
    <p>黎明时，星港的灯逐一熄灭。</p>
    <p>“准备好了吗？”领航员问。</p>
    <p>舷窗外写着<ruby>星<rt>せい</rt></ruby>的旧标记仍然清晰。</p>
    <img src="images/diagram.png" alt="星港航线图" title="第一幅航线图"/>
    <p><a href="chapter-2.xhtml#arrival">继续前往第二章</a></p>
    <script type="text/javascript">const untranslated = "不要翻译脚本";</script>
  </article></body>
</html>
"""),
            zipfile.ZIP_DEFLATED,
        ),
        (
            "EPUB/chapter-2.xhtml",
            _utf8("""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-CN" xml:lang="zh-CN">
  <head><title>第二章 抵达</title><link rel="stylesheet" href="styles/book.css"/></head>
  <body><article id="arrival"><h1>第二章 抵达</h1>
    <p>短暂的跃迁之后，新世界出现在眼前。</p>
    <p>船员把这一天写进共同的航海日志。<a epub:type="noteref"
      xmlns:epub="http://www.idpf.org/2007/ops" href="notes.xhtml#note-1">1</a></p>
    <p><a href="chapter-1.xhtml#departure">返回第一章</a></p>
  </article></body>
</html>
"""),
            zipfile.ZIP_DEFLATED,
        ),
        (
            "EPUB/notes.xhtml",
            _utf8("""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
  xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN" xml:lang="zh-CN">
  <head><title>注释</title><link rel="stylesheet" href="styles/book.css"/></head>
  <body><section id="notes"><h1>注释</h1><aside epub:type="footnote" id="note-1">
    这是一条保留内部链接的脚注。
  </aside></section></body>
</html>
"""),
            zipfile.ZIP_DEFLATED,
        ),
        (
            "EPUB/styles/book.css",
            b"body { color: #17243a; background-image: url('../images/paper.png'); }\n"
            b"img { max-width: 100%; } ruby rt { font-size: 0.55em; }\n",
            zipfile.ZIP_DEFLATED,
        ),
        ("EPUB/images/cover.png", _png(96, 128, (38, 91, 143)), zipfile.ZIP_STORED),
        ("EPUB/images/diagram.png", _png(80, 48, (103, 153, 184)), zipfile.ZIP_STORED),
        ("EPUB/images/paper.png", _png(8, 8, (238, 235, 224)), zipfile.ZIP_STORED),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload, compression in entries:
            _write_zip_member(archive, name, payload, compression)


def _create_txt(path: Path) -> None:
    path.write_text(
        """第一章 夜航

星港沉入夜色，最后一班渡船悄然离岸。

“记住我们的约定。”她说。

第二章 回声

晨光越过舷窗时，他们听见了遥远的回声。
""",
        encoding="utf-8",
        newline="\n",
    )


def _create_cbz(path: Path) -> None:
    pages = (
        ("pages/001.png", _png(96, 128, (209, 82, 69))),
        ("pages/002.png", _png(96, 128, (69, 132, 209))),
    )
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in pages:
            _write_zip_member(archive, name, payload)


def _create_large_epub(path: Path) -> None:
    chapter_items = "\n".join(
        f'    <item id="c{index:03d}" href="chapters/c{index:03d}.xhtml" '
        'media-type="application/xhtml+xml"/>'
        for index in range(LARGE_CHAPTER_COUNT)
    )
    resource_items = "\n".join(
        f'    <item id="r{index:03d}" href="resources/r{index:03d}.bin" '
        'media-type="application/octet-stream"/>'
        for index in range(LARGE_AUXILIARY_RESOURCE_COUNT)
    )
    spine_items = "\n".join(
        f'    <itemref idref="c{index:03d}"/>' for index in range(LARGE_CHAPTER_COUNT)
    )
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:uuid:de8a825b-431c-55e8-a8d4-cec5f66b7564</dc:identifier>
    <dc:title>Representative Large Fixture</dc:title>
    <dc:language>en</dc:language>
    <meta property="dcterms:modified">2020-01-02T03:04:06Z</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="large" href="resources/large.bin" media-type="application/octet-stream"/>
{chapter_items}
{resource_items}
  </manifest>
  <spine>
{spine_items}
  </spine>
</package>
""".encode()
    container = b"""<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="EPUB/content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""
    nav = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
  xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">
  <head><title>Contents</title></head><body><nav epub:type="toc"><ol>
    <li><a href="chapters/c000.xhtml">First</a></li>
    <li><a href="chapters/c259.xhtml">Last</a></li>
  </ol></nav></body>
</html>
"""
    repeated_megabyte = bytes(range(256)) * 4096
    with zipfile.ZipFile(path, "w") as archive:
        _write_zip_member(archive, "mimetype", b"application/epub+zip", zipfile.ZIP_STORED)
        _write_zip_member(archive, "META-INF/container.xml", container)
        _write_zip_member(archive, "EPUB/content.opf", opf)
        _write_zip_member(archive, "EPUB/nav.xhtml", nav)
        for index in range(LARGE_CHAPTER_COUNT):
            chapter = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en">
  <head><title>Chapter {index:03d}</title></head>
  <body><h1>Chapter {index:03d}</h1><p>Deterministic representative text {index:03d}.</p></body>
</html>
""".encode()
            _write_zip_member(archive, f"EPUB/chapters/c{index:03d}.xhtml", chapter)
        for index in range(LARGE_AUXILIARY_RESOURCE_COUNT):
            payload = hashlib.sha256(f"resource-{index:03d}".encode()).digest() * 4
            _write_zip_member(
                archive,
                f"EPUB/resources/r{index:03d}.bin",
                payload,
                zipfile.ZIP_STORED,
            )
        large_info = _zip_info("EPUB/resources/large.bin", zipfile.ZIP_STORED)
        with archive.open(large_info, "w") as target:
            for _ in range(LARGE_RESOURCE_BYTES // len(repeated_megabyte)):
                target.write(repeated_megabyte)


def _deterministic_id_factory() -> Callable[[], str]:
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return str(uuid.uuid5(ID_NAMESPACE, f"linguaspindle-v020-acceptance-{counter:05d}"))

    return next_id


@contextmanager
def _deterministic_zip_writes() -> Iterator[None]:
    """Fix timestamps for ZipFile.writestr calls made with a plain archive name."""

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
            target = _zip_info(zinfo_or_arcname, compress_type or archive.compression)
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


def _select_artifact(artifacts: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = [artifact for artifact in artifacts if artifact["kind"] == kind]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {kind} Artifact, found {len(matches)}")
    return matches[0]


def _copy_artifact(
    service: ApplicationService,
    artifact: Mapping[str, Any],
    destination: Path,
) -> dict[str, Any]:
    service.copy_artifact(str(artifact["id"]), destination)
    destination.chmod(0o644)
    checksum = _sha256(destination)
    if checksum != artifact["checksum"]:
        raise RuntimeError(f"Copied Artifact checksum mismatch: {destination}")
    return {
        "artifact_id": artifact["id"],
        "artifact_kind": artifact["kind"],
        "path": destination.as_posix(),
        "bytes": destination.stat().st_size,
        "sha256": checksum,
    }


def _compact_job(job: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "project_id": job["project_id"],
        "pipeline_key": job["pipeline_key"],
        "provider_id": job["provider_id"],
        "adapter_id": job["adapter_id"],
        "status": job["status"],
        "progress": job["progress"],
        "error": job["error"],
        "steps": [
            {
                "id": step["id"],
                "key": step["key"],
                "order": step["order"],
                "capability": step["capability"],
                "executor_type": step["executor_type"],
                "executor_id": step["executor_id"],
                "status": step["status"],
                "attempt_count": step["attempt_count"],
                "input_artifact_ids": step["input_artifact_ids"],
                "output_artifact_ids": step["output_artifact_ids"],
                "error": step["error"],
            }
            for step in job["steps"]
        ],
    }


def _compact_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": artifact["id"],
            "project_id": artifact["project_id"],
            "job_id": artifact["job_id"],
            "step_run_id": artifact["step_run_id"],
            "kind": artifact["kind"],
            "filename": artifact["filename"],
            "media_type": artifact["media_type"],
            "bytes": artifact["size"],
            "sha256": artifact["checksum"],
            "lineage": {
                key: value
                for key, value in artifact["metadata"].items()
                if key.endswith("_id") or key.endswith("_ids")
            },
        }
        for artifact in artifacts
    ]


def _run_project(
    service: ApplicationService,
    runner: JobRunner,
    *,
    name: str,
    kind: str,
    source_language: str,
    target_language: str,
    source_path: Path,
    pipeline_key: str,
    adapter_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    project = service.create_project_from_path(
        name=name,
        kind=kind,
        source_language=source_language,
        target_language=target_language,
        source_path=source_path,
    )
    profile = service.create_profile(
        name=f"Acceptance profile for {name}",
        source_language=source_language,
        target_language=target_language,
        provider_id="mock",
        model="mock-v1",
    )
    with service.database.session() as session:
        profile_row = session.get(TranslationProfile, profile["id"])
        if profile_row is None:
            raise RuntimeError("Acceptance Translation Profile was not persisted")
        profile_row.created_at = FIXED_RUNTIME_TIME
        profile_row.updated_at = FIXED_RUNTIME_TIME
    job = service.create_job(
        project_id=project["id"],
        pipeline_key=pipeline_key,
        profile_id=profile["id"],
        provider_id="mock",
        adapter_id=adapter_id,
    )
    terminal = runner.run_until_terminal(job["id"])
    if terminal["status"] != "succeeded":
        raise RuntimeError(
            f"Acceptance {pipeline_key} Job ended as {terminal['status']}: {terminal['error']}"
        )
    detailed = service.get_project(project["id"])
    artifacts = service.list_artifacts(project_id=project["id"])
    return detailed, terminal, artifacts


def _verify_zip(path: Path, expected_suffix: str) -> dict[str, Any]:
    if path.suffix.lower() != expected_suffix:
        raise RuntimeError(f"Unexpected archive suffix: {path}")
    with zipfile.ZipFile(path, "r") as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise RuntimeError(f"Archive CRC failure in {path}: {bad_member}")
        files = [entry for entry in archive.infolist() if not entry.is_dir()]
        for entry in files:
            archive.read(entry)
    return {"openable": True, "crc_valid": True, "member_count": len(files)}


def _verify_epub_resources(source: Path, output: Path) -> dict[str, Any]:
    resource_paths = (
        "EPUB/styles/book.css",
        "EPUB/images/cover.png",
        "EPUB/images/diagram.png",
        "EPUB/images/paper.png",
    )
    with zipfile.ZipFile(source, "r") as original, zipfile.ZipFile(output, "r") as translated:
        equality = {path: original.read(path) == translated.read(path) for path in resource_paths}
        output_text = "\n".join(
            translated.read(path).decode("utf-8")
            for path in translated.namelist()
            if path.endswith((".xhtml", ".opf"))
        )
    if not all(equality.values()):
        raise RuntimeError("The translated EPUB changed a preserved sample resource")
    if "[en]" not in output_text:
        raise RuntimeError("The translated EPUB contains no Mock Provider marker")
    protected_content = {
        "script_text_not_translated": (
            "不要翻译脚本" in output_text and "[en] 不要翻译脚本" not in output_text
        ),
        "ruby_pronunciation_preserved": "せい" in output_text,
        "internal_chapter_link_preserved": "chapter-2.xhtml#arrival" in output_text,
        "footnote_link_preserved": "notes.xhtml#note-1" in output_text,
    }
    if not all(protected_content.values()):
        raise RuntimeError("The translated EPUB changed protected content or internal links")
    return {
        "byte_equal_preserved_resources": equality,
        "mock_translation_marker_present": True,
        **protected_content,
    }


def _relative_files(files: list[dict[str, Any]], repository: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in files:
        copied = dict(item)
        copied["path"] = Path(str(item["path"])).relative_to(repository).as_posix()
        result.append(copied)
    return result


def _generate_samples(repository: Path) -> dict[str, Any]:
    artifacts_root = repository / "acceptance" / "v0.2.0" / "artifacts"
    samples_root = artifacts_root / "samples"
    owned_files = (
        samples_root / "epub" / "source-multichapter.epub",
        samples_root / "epub" / "translated-multichapter.epub",
        samples_root / "epub" / "validation-report.json",
        samples_root / "txt" / "source.txt",
        samples_root / "txt" / "translated.txt",
        samples_root / "txt" / "translated.json",
        samples_root / "manga" / "source.cbz",
        samples_root / "manga" / "translated.cbz",
        artifacts_root / "sample-run-summary.json",
    )
    for path in owned_files:
        path.unlink(missing_ok=True)

    original_new_id: Callable[[], str] = application_module.new_id  # type: ignore[attr-defined]
    application_module.new_id = _deterministic_id_factory()  # type: ignore[attr-defined]
    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="linguaspindle-v020-acceptance-") as temporary:
        data_root = Path(temporary).resolve()
        settings = Settings(data_dir=data_root, openai_api_key=None)
        service = ApplicationService(settings)
        runner = JobRunner(service)
        try:
            fixtures = settings.cache_dir / "acceptance-fixtures"
            fixtures.mkdir(parents=True, exist_ok=True)
            epub_source = fixtures / "source-multichapter.epub"
            txt_source = fixtures / "source.txt"
            manga_source = fixtures / "source.cbz"
            _create_sample_epub(epub_source)
            _create_txt(txt_source)
            _create_cbz(manga_source)

            epub_project, epub_job, epub_artifacts = _run_project(
                service,
                runner,
                name="EPUB Round Trip",
                kind="novel",
                source_language="zh-CN",
                target_language="en",
                source_path=epub_source,
                pipeline_key="novel_epub_v1",
            )
            epub_source_artifact = _select_artifact(epub_artifacts, "source_original")
            epub_output_artifact = _select_artifact(epub_artifacts, "novel_export_epub")
            validation_artifact = _select_artifact(epub_artifacts, "epub_validation_report")
            epub_files = [
                _copy_artifact(
                    service,
                    epub_source_artifact,
                    samples_root / "epub" / "source-multichapter.epub",
                ),
                _copy_artifact(
                    service,
                    epub_output_artifact,
                    samples_root / "epub" / "translated-multichapter.epub",
                ),
                _copy_artifact(
                    service,
                    validation_artifact,
                    samples_root / "epub" / "validation-report.json",
                ),
            ]
            source_epub_path = samples_root / "epub" / "source-multichapter.epub"
            output_epub_path = samples_root / "epub" / "translated-multichapter.epub"
            source_inspection = inspect_epub(source_epub_path, settings.archive_limits())
            output_inspection = inspect_epub(output_epub_path, settings.archive_limits())
            epub_verification = {
                "source_archive": _verify_zip(source_epub_path, ".epub"),
                "output_archive": _verify_zip(output_epub_path, ".epub"),
                "source_valid": source_inspection["validation"]["valid"],
                "output_valid": output_inspection["validation"]["valid"],
                "source_language": source_inspection["metadata"]["languages"],
                "output_language": output_inspection["metadata"]["languages"],
                "creator_display_only_preserved": (
                    source_inspection["metadata"]["creators"]
                    == output_inspection["metadata"]["creators"]
                ),
                **_verify_epub_resources(source_epub_path, output_epub_path),
            }
            if "en" not in output_inspection["metadata"]["languages"]:
                raise RuntimeError("Translated EPUB package language is not en")
            if not epub_verification["creator_display_only_preserved"]:
                raise RuntimeError("Translated EPUB changed display-only creator metadata")
            cases.append(
                {
                    "case": "epub3_round_trip",
                    "mock_execution": {"provider_id": "mock", "model": "mock-v1"},
                    "project": {
                        "id": epub_project["id"],
                        "kind": epub_project["kind"],
                        "source_language": epub_project["source_language"],
                        "target_language": epub_project["target_language"],
                        "sources": [
                            {
                                key: source[key]
                                for key in (
                                    "id",
                                    "kind",
                                    "artifact_id",
                                    "original_name",
                                    "size",
                                    "checksum",
                                    "metadata",
                                )
                            }
                            for source in epub_project["sources"]
                        ],
                    },
                    "job": _compact_job(epub_job),
                    "artifacts": _compact_artifacts(epub_artifacts),
                    "delivered_files": _relative_files(epub_files, repository),
                    "verification": epub_verification,
                }
            )

            txt_project, txt_job, txt_artifacts = _run_project(
                service,
                runner,
                name="TXT Regression",
                kind="novel",
                source_language="zh-CN",
                target_language="en",
                source_path=txt_source,
                pipeline_key="novel_txt_v1",
            )
            txt_source_artifact = _select_artifact(txt_artifacts, "source_original")
            txt_output_artifact = _select_artifact(txt_artifacts, "novel_export_txt")
            json_output_artifact = _select_artifact(txt_artifacts, "novel_export_json")
            txt_files = [
                _copy_artifact(
                    service,
                    txt_source_artifact,
                    samples_root / "txt" / "source.txt",
                ),
                _copy_artifact(
                    service,
                    txt_output_artifact,
                    samples_root / "txt" / "translated.txt",
                ),
                _copy_artifact(
                    service,
                    json_output_artifact,
                    samples_root / "txt" / "translated.json",
                ),
            ]
            translated_txt = (samples_root / "txt" / "translated.txt").read_text(encoding="utf-8")
            translated_json = json.loads(
                (samples_root / "txt" / "translated.json").read_text(encoding="utf-8")
            )
            if "[en]" not in translated_txt or translated_json["job_id"] != txt_job["id"]:
                raise RuntimeError("TXT/JSON Mock export verification failed")
            cases.append(
                {
                    "case": "txt_regression",
                    "mock_execution": {"provider_id": "mock", "model": "mock-v1"},
                    "project": {
                        "id": txt_project["id"],
                        "kind": txt_project["kind"],
                        "source_language": txt_project["source_language"],
                        "target_language": txt_project["target_language"],
                        "sources": [
                            {
                                key: source[key]
                                for key in (
                                    "id",
                                    "kind",
                                    "artifact_id",
                                    "original_name",
                                    "size",
                                    "checksum",
                                )
                            }
                            for source in txt_project["sources"]
                        ],
                    },
                    "job": _compact_job(txt_job),
                    "artifacts": _compact_artifacts(txt_artifacts),
                    "delivered_files": _relative_files(txt_files, repository),
                    "verification": {
                        "mock_translation_marker_present": True,
                        "json_job_lineage_matches": True,
                        "source_immutable_checksum_matches": (
                            txt_files[0]["sha256"] == txt_project["sources"][0]["checksum"]
                        ),
                    },
                }
            )

            with _deterministic_zip_writes():
                manga_project, manga_job, manga_artifacts = _run_project(
                    service,
                    runner,
                    name="Manga Mock Regression",
                    kind="manga",
                    source_language="ja",
                    target_language="en",
                    source_path=manga_source,
                    pipeline_key="manga_full_v1",
                    adapter_id="mock-manga",
                )
            manga_source_artifact = _select_artifact(manga_artifacts, "source_original")
            manga_output_artifact = _select_artifact(manga_artifacts, "manga_export_cbz")
            manga_files = [
                _copy_artifact(
                    service,
                    manga_source_artifact,
                    samples_root / "manga" / "source.cbz",
                ),
                _copy_artifact(
                    service,
                    manga_output_artifact,
                    samples_root / "manga" / "translated.cbz",
                ),
            ]
            manga_source_check = _verify_zip(samples_root / "manga" / "source.cbz", ".cbz")
            manga_output_check = _verify_zip(samples_root / "manga" / "translated.cbz", ".cbz")
            if manga_source_check["member_count"] != manga_output_check["member_count"]:
                raise RuntimeError("Mock manga export page count changed")
            cases.append(
                {
                    "case": "manga_cbz_mock_regression",
                    "mock_execution": {
                        "provider_id": "mock",
                        "adapter_id": "mock-manga",
                        "adapter_type": "built-in deterministic offline mock",
                    },
                    "project": {
                        "id": manga_project["id"],
                        "kind": manga_project["kind"],
                        "source_language": manga_project["source_language"],
                        "target_language": manga_project["target_language"],
                        "sources": [
                            {
                                key: source[key]
                                for key in (
                                    "id",
                                    "kind",
                                    "artifact_id",
                                    "original_name",
                                    "size",
                                    "checksum",
                                )
                            }
                            for source in manga_project["sources"]
                        ],
                    },
                    "job": _compact_job(manga_job),
                    "artifacts": _compact_artifacts(manga_artifacts),
                    "delivered_files": _relative_files(manga_files, repository),
                    "verification": {
                        "source_archive": manga_source_check,
                        "output_archive": manga_output_check,
                        "page_count_preserved": True,
                        "zip_timestamps_fixed_by_acceptance_harness": True,
                    },
                }
            )
        finally:
            service.close()
            application_module.new_id = original_new_id  # type: ignore[attr-defined]

    summary = {
        "schema_version": 1,
        "milestone": "v0.2.0",
        "generator": "tools/generate_v020_acceptance.py",
        "execution_boundary": "ApplicationService + JobRunner",
        "network_used": False,
        "paid_provider_used": False,
        "mock_only": True,
        "determinism": {
            "fixture_payloads": "fixed",
            "application_ids": "UUIDv5 sequence fixed by acceptance harness",
            "zip_member_timestamps": FIXED_ZIP_TIME,
            "runtime_database": "temporary and removed after generation",
        },
        "cases": cases,
    }
    summary_path = artifacts_root / "sample-run-summary.json"
    _atomic_write(summary_path, _json_bytes(summary))
    return summary


def _peak_rss_bytes() -> tuple[int | None, str]:
    try:
        import resource
    except ImportError:
        return None, "resource module unavailable"
    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return raw, "ru_maxrss bytes on macOS"
    return raw * 1024, "ru_maxrss KiB normalized to bytes"


def _measurement_worker(epub_path: Path, data_root: Path) -> dict[str, Any]:
    settings = Settings(data_dir=data_root.resolve(), openai_api_key=None)
    started = time.perf_counter()
    inspection = inspect_epub(epub_path.resolve(), settings.archive_limits())
    elapsed = time.perf_counter() - started
    peak_rss, peak_rss_basis = _peak_rss_bytes()
    validation = inspection["validation"]
    entries = inspection["entries"]
    return {
        "inspection": {
            "valid": validation["valid"],
            "member_count": validation["member_count"],
            "expanded_bytes": validation["expanded_bytes"],
            "compressed_payload_bytes": validation["compressed_bytes"],
            "maximum_member_expanded_bytes": max(entry["size"] for entry in entries),
            "maximum_compression_ratio": validation["maximum_compression_ratio"],
            "maximum_path_depth": max(len(str(entry["path"]).split("/")) for entry in entries),
            "document_count": validation["document_count"],
            "text_unit_count": validation["text_unit_count"],
            "elapsed_seconds": round(elapsed, 6),
            "process_peak_rss_bytes": peak_rss,
            "process_peak_rss_basis": peak_rss_basis,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
        },
    }


def _ratio(limit: int | float, observed: int | float) -> float | None:
    if observed <= 0:
        return None
    return round(float(limit) / float(observed), 4)


def _measure_large_epub(repository: Path) -> dict[str, Any]:
    evidence_path = (
        repository / "acceptance" / "v0.2.0" / "evidence" / ("resource-measurements.json")
    )
    with tempfile.TemporaryDirectory(prefix="linguaspindle-v020-resource-") as temporary:
        root = Path(temporary).resolve()
        data_root = root / "data"
        data_root.mkdir(parents=True)
        fixture = data_root / "cache" / "representative-large.epub"
        fixture.parent.mkdir(parents=True)
        _create_large_epub(fixture)
        fixture_checksum = _sha256(fixture)
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--measure-worker",
            str(fixture),
            "--worker-data-root",
            str(data_root / "worker"),
        ]
        worker_environment = dict(os.environ)
        worker_environment.pop("LINGUASPINDLE_OPENAI_API_KEY", None)
        completed = subprocess.run(  # noqa: S603
            command,
            check=True,
            capture_output=True,
            text=True,
            cwd=repository,
            env=worker_environment,
        )
        worker = json.loads(completed.stdout)
        settings = Settings(data_dir=data_root / "limits", openai_api_key=None)
        inspection = worker["inspection"]
        defaults = {
            "max_upload_bytes": settings.max_upload_bytes,
            "max_archive_files": settings.max_archive_files,
            "max_archive_uncompressed_bytes": settings.max_archive_uncompressed_bytes,
            "max_archive_member_bytes": settings.max_archive_member_bytes,
            "max_archive_compression_ratio": settings.max_archive_compression_ratio,
            "max_archive_path_depth": settings.max_archive_path_depth,
        }
        sample = {
            "schema_version": 1,
            "milestone": "v0.2.0",
            "measurement": "inspect_epub in a fresh subprocess",
            "fixture": {
                "committed": False,
                "temporary_only": True,
                "sha256": fixture_checksum,
                "input_bytes": fixture.stat().st_size,
                "requested_large_resource_bytes": LARGE_RESOURCE_BYTES,
                "requested_chapter_count": LARGE_CHAPTER_COUNT,
                "requested_auxiliary_resource_count": LARGE_AUXILIARY_RESOURCE_COUNT,
                "construction": (
                    "deterministic EPUB3 with a stored 24 MiB binary resource, 260 XHTML "
                    "chapters, and 240 stored auxiliary resources"
                ),
            },
            **worker,
            "default_limits": defaults,
            "limit_headroom_multiples": {
                "upload_bytes": _ratio(defaults["max_upload_bytes"], fixture.stat().st_size),
                "archive_members": _ratio(
                    defaults["max_archive_files"], inspection["member_count"]
                ),
                "expanded_bytes": _ratio(
                    defaults["max_archive_uncompressed_bytes"], inspection["expanded_bytes"]
                ),
                "largest_member_bytes": _ratio(
                    defaults["max_archive_member_bytes"],
                    inspection["maximum_member_expanded_bytes"],
                ),
                "maximum_compression_ratio": _ratio(
                    defaults["max_archive_compression_ratio"],
                    inspection["maximum_compression_ratio"],
                ),
                "path_depth": _ratio(
                    defaults["max_archive_path_depth"], inspection["maximum_path_depth"]
                ),
            },
            "limitations": [
                "One cold subprocess sample on the recorded host; elapsed time and peak RSS vary.",
                "The 24 MiB resource is ZIP_STORED, so this is not a compression-bomb sample.",
                (
                    "Inspection reads and validates every member but does not invoke Provider "
                    "translation."
                ),
                (
                    "The fixture is synthetic and does not predict reader rendering or publisher "
                    "CSS cost."
                ),
                "The default thresholds are safety bounds, not throughput or memory guarantees.",
            ],
        }
        _atomic_write(evidence_path, _json_bytes(sample))
    return sample


def main() -> int:
    arguments = _arguments()
    if arguments.measure_worker is not None:
        if arguments.worker_data_root is None:
            raise SystemExit("--worker-data-root is required with --measure-worker")
        print(
            json.dumps(
                _measurement_worker(arguments.measure_worker, arguments.worker_data_root),
                sort_keys=True,
            )
        )
        return 0

    repository = arguments.repository.expanduser().resolve()
    if not (repository / "pyproject.toml").is_file():
        raise SystemExit(f"Not a LinguaSpindle repository: {repository}")
    _generate_samples(repository)
    _measure_large_epub(repository)
    _assert_no_active_provider_secrets(repository)
    print("Generated v0.2.0 samples and resource measurements with offline Mock execution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
