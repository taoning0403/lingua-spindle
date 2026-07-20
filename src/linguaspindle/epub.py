"""Safe, dependency-free inspection and rebuilding of unencrypted EPUB files.

The module deliberately works on paths and plain JSON-compatible dictionaries.  It does not
know about Projects, Jobs, database rows, or Artifact storage, which lets every interface call it
through the existing application/orchestration boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import stat
import tempfile
import unicodedata
import zipfile
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, NoReturn, cast
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from linguaspindle.errors import ErrorCode, LinguaError

if TYPE_CHECKING:
    from linguaspindle.config import Settings

_CONTAINER_PATH = "META-INF/container.xml"
_MIMETYPE_PATH = "mimetype"
_EPUB_MIMETYPE = b"application/epub+zip"
_ENCRYPTION_PATH = "meta-inf/encryption.xml"
_PACKAGE_MEDIA_TYPE = "application/oebps-package+xml"
_XHTML_MEDIA_TYPES = frozenset({"application/xhtml+xml", "text/html"})
_NCX_MEDIA_TYPE = "application/x-dtbncx+xml"
_XML_MEDIA_TYPES = frozenset(
    {
        _PACKAGE_MEDIA_TYPE,
        "application/xhtml+xml",
        "application/x-dtbncx+xml",
        "application/xml",
        "image/svg+xml",
        "text/xml",
    }
)
_SKIPPED_ELEMENTS = frozenset({"script", "style", "code", "svg", "rt", "rp"})
_RESOURCE_ATTRIBUTES = frozenset({"data", "href", "poster", "src"})
_EXTERNAL_SCHEMES = frozenset({"data", "ftp", "http", "https", "mailto", "tel"})
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_CSS_URL_RE = re.compile(
    r"(?:url\(\s*|@import\s+)(?P<quote>['\"]?)(?P<uri>[^'\")\s;]+)(?P=quote)\s*\)?",
    re.IGNORECASE,
)
_LEADING_TRAILING_RE = re.compile(r"^(\s*)(.*?)(\s*)$", re.DOTALL)
_SAFE_DOCTYPE_RE = re.compile(
    rb"""
    <!DOCTYPE\s+[A-Z_:][A-Z0-9_.:-]*
    (?:
        \s+SYSTEM\s+(?:"[^"<>\[\]]*"|'[^'<>\[\]]*')
        |
        \s+PUBLIC\s+(?:"[^"<>\[\]]*"|'[^'<>\[\]]*')
        \s+(?:"[^"<>\[\]]*"|'[^'<>\[\]]*')
    )?
    \s*>
    """,
    re.IGNORECASE | re.VERBOSE,
)

_DEFAULT_MAX_FILES = 2_000
_DEFAULT_MAX_TOTAL_BYTES = 1_000 * 1024 * 1024
_DEFAULT_MAX_MEMBER_BYTES = 100 * 1024 * 1024
_DEFAULT_MAX_COMPRESSION_RATIO = 100.0
_DEFAULT_MAX_PATH_DEPTH = 20
_READ_CHUNK_BYTES = 1024 * 1024
_MAX_TEXT_UNIT_CHARS = 1_800
_SENTENCE_ENDINGS = frozenset(".!?。！？；;")

_DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
_EPUB_NAMESPACE = "http://www.idpf.org/2007/ops"
_KNOWN_NAMESPACES = {
    "dc": _DC_NAMESPACE,
    "epub": _EPUB_NAMESPACE,
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "opf": "http://www.idpf.org/2007/opf",
    "xhtml": "http://www.w3.org/1999/xhtml",
}


def _error_code(name: str, fallback: ErrorCode = ErrorCode.INVALID_FORMAT) -> ErrorCode:
    """Use v0.2 codes when present while remaining importable during the migration."""

    return cast(ErrorCode, getattr(ErrorCode, name, fallback))


def _error_code_any(*names: str, fallback: ErrorCode = ErrorCode.INVALID_FORMAT) -> ErrorCode:
    for name in names:
        code = getattr(ErrorCode, name, None)
        if isinstance(code, ErrorCode):
            return code
    return fallback


def _invalid(message: str, details: dict[str, Any] | None = None) -> NoReturn:
    raise LinguaError(_error_code("EPUB_INVALID"), message, details)


def _resource_limit(message: str, details: dict[str, Any]) -> NoReturn:
    raise LinguaError(_error_code_any("RESOURCE_LIMIT", "ARCHIVE_LIMIT_EXCEEDED"), message, details)


def _unsupported_protection(message: str, details: dict[str, Any] | None = None) -> NoReturn:
    raise LinguaError(_error_code_any("UNSUPPORTED_PROTECTION", "EPUB_PROTECTED"), message, details)


def _unsafe_archive(message: str, details: dict[str, Any] | None = None) -> NoReturn:
    raise LinguaError(_error_code("ARCHIVE_UNSAFE"), message, details)


def _unsupported_format(message: str, details: dict[str, Any] | None = None) -> NoReturn:
    raise LinguaError(_error_code("EPUB_UNSUPPORTED"), message, details)


def _validation_failed(details: dict[str, Any] | None = None) -> NoReturn:
    raise LinguaError(
        _error_code("EPUB_VALIDATION_FAILED"),
        "Translated EPUB failed independent validation",
        details,
    )


def _setting_number(settings: Settings | None, name: str, default: int | float) -> int | float:
    value = getattr(settings, name, default) if settings is not None else default
    if isinstance(default, float):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return default
        return result if result > 0 else default
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


def _limits(settings: Settings | None) -> dict[str, int | float]:
    return {
        "max_archive_files": _setting_number(settings, "max_archive_files", _DEFAULT_MAX_FILES),
        "max_archive_uncompressed_bytes": _setting_number(
            settings,
            "max_archive_uncompressed_bytes",
            _DEFAULT_MAX_TOTAL_BYTES,
        ),
        "max_archive_member_bytes": _setting_number(
            settings, "max_archive_member_bytes", _DEFAULT_MAX_MEMBER_BYTES
        ),
        "max_archive_compression_ratio": _setting_number(
            settings,
            "max_archive_compression_ratio",
            _DEFAULT_MAX_COMPRESSION_RATIO,
        ),
        "max_archive_path_depth": _setting_number(
            settings, "max_archive_path_depth", _DEFAULT_MAX_PATH_DEPTH
        ),
    }


def _contains_control_character(value: str) -> bool:
    return any(ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in value)


def _canonical_member_name(name: str, max_depth: int) -> str:
    if not name or "\x00" in name or "\\" in name:
        _unsafe_archive("EPUB contains an unsafe ZIP member path", {"member": name})
    if _contains_control_character(name):
        _unsafe_archive("EPUB contains a control character in a ZIP member path", {"member": name})
    raw_parts = name.split("/")
    if name.endswith("/"):
        raw_parts = raw_parts[:-1]
    if not raw_parts or any(part in {"", ".", ".."} for part in raw_parts):
        _unsafe_archive("EPUB contains an unsafe ZIP member path", {"member": name})
    candidate = PurePosixPath(name)
    parts = candidate.parts
    if candidate.is_absolute() or not parts:
        _unsafe_archive("EPUB contains an unsafe ZIP member path", {"member": name})
    if ":" in parts[0]:
        _unsafe_archive("EPUB contains an unsafe ZIP member path", {"member": name})
    if len(parts) > max_depth:
        _resource_limit(
            "EPUB member path exceeds the configured depth limit",
            {"member": name, "depth": len(parts), "limit": max_depth},
        )
    return "/".join(parts)


def _portable_name(name: str) -> str:
    return unicodedata.normalize("NFC", name.rstrip("/")).casefold()


def _is_symlink(member: zipfile.ZipInfo) -> bool:
    mode = member.external_attr >> 16
    return member.create_system == 3 and stat.S_IFMT(mode) == stat.S_IFLNK


def _compression_ratio(member: zipfile.ZipInfo) -> float:
    if member.file_size == 0:
        return 0.0
    if member.compress_size <= 0:
        return float("inf")
    return member.file_size / member.compress_size


def _validate_archive_entries(
    archive: zipfile.ZipFile, settings: Settings | None
) -> tuple[dict[str, zipfile.ZipInfo], dict[str, Any]]:
    limits = _limits(settings)
    infos = archive.infolist()
    max_files = int(limits["max_archive_files"])
    if len(infos) > max_files:
        _resource_limit(
            "EPUB contains too many ZIP members",
            {"member_count": len(infos), "limit": max_files},
        )
    if not infos:
        _invalid("EPUB ZIP archive is empty")

    max_member = int(limits["max_archive_member_bytes"])
    max_total = int(limits["max_archive_uncompressed_bytes"])
    max_ratio = float(limits["max_archive_compression_ratio"])
    max_depth = int(limits["max_archive_path_depth"])
    members: dict[str, zipfile.ZipInfo] = {}
    portable_names: set[str] = set()
    announced_total = 0
    observed_max_ratio = 0.0

    for member in infos:
        name = _canonical_member_name(member.filename, max_depth)
        portable = _portable_name(name)
        if name in members or portable in portable_names:
            _unsafe_archive(
                "EPUB contains duplicate or ambiguous ZIP member paths", {"member": name}
            )
        members[name] = member
        portable_names.add(portable)
        if member.flag_bits & 0x41:
            _unsupported_protection("Encrypted EPUB content is not supported", {"member": name})
        if _is_symlink(member):
            _unsafe_archive("EPUB ZIP members cannot be symbolic links", {"member": name})
        if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            _unsupported_format(
                "EPUB uses an unsupported ZIP compression method",
                {"member": name, "compression_method": member.compress_type},
            )
        if member.file_size < 0 or member.compress_size < 0:
            _invalid("EPUB contains an invalid ZIP member size", {"member": name})
        if member.file_size > max_member:
            _resource_limit(
                "EPUB member exceeds the configured expanded-size limit",
                {"member": name, "expanded_bytes": member.file_size, "limit": max_member},
            )
        announced_total += member.file_size
        if announced_total > max_total:
            _resource_limit(
                "EPUB expands beyond the configured total-size limit",
                {"expanded_bytes": announced_total, "limit": max_total},
            )
        ratio = _compression_ratio(member)
        observed_max_ratio = max(observed_max_ratio, ratio)
        if ratio > max_ratio:
            _resource_limit(
                "EPUB member exceeds the configured compression-ratio limit",
                {
                    "member": name,
                    "compression_ratio": "infinite" if ratio == float("inf") else ratio,
                    "limit": max_ratio,
                },
            )

    if _portable_name(_ENCRYPTION_PATH) in portable_names:
        _unsupported_protection(
            "EPUB encryption metadata is present; protected EPUBs are not supported"
        )

    # Read every payload in bounded chunks.  This verifies CRCs and the actual expanded byte
    # counts instead of trusting only the central directory supplied by an attacker.
    actual_total = 0
    try:
        for name, member in members.items():
            if member.is_dir():
                continue
            actual_member = 0
            with archive.open(member, "r") as stream:
                while True:
                    chunk = stream.read(_READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    actual_member += len(chunk)
                    actual_total += len(chunk)
                    if actual_member > max_member:
                        _resource_limit(
                            "EPUB member exceeds the configured expanded-size limit",
                            {"member": name, "expanded_bytes": actual_member, "limit": max_member},
                        )
                    if actual_total > max_total:
                        _resource_limit(
                            "EPUB expands beyond the configured total-size limit",
                            {"expanded_bytes": actual_total, "limit": max_total},
                        )
            if actual_member != member.file_size:
                _invalid(
                    "EPUB ZIP member size does not match its directory entry",
                    {"member": name},
                )
    except LinguaError:
        raise
    except (
        BadZipfileError,
        NotImplementedError,
        OSError,
        RuntimeError,
        EOFError,
        ValueError,
        zipfile.LargeZipFile,
        zlib.error,
    ) as exc:
        _invalid("EPUB contains a damaged ZIP member", {"reason": type(exc).__name__})

    return members, {
        "member_count": len(infos),
        "expanded_bytes": actual_total,
        "compressed_bytes": sum(item.compress_size for item in infos),
        "maximum_compression_ratio": observed_max_ratio,
        "limits": limits,
    }


# Python exposes BadZipFile today; the alias keeps the exception tuple readable and compatible.
BadZipfileError = zipfile.BadZipFile


def _read_member(
    archive: zipfile.ZipFile, members: Mapping[str, zipfile.ZipInfo], name: str
) -> bytes:
    member = members.get(name)
    if member is None or member.is_dir():
        _invalid("EPUB is missing a required file", {"member": name})
    try:
        return archive.read(member)
    except (
        BadZipfileError,
        EOFError,
        NotImplementedError,
        OSError,
        RuntimeError,
        ValueError,
        zlib.error,
    ) as exc:
        _invalid(
            "EPUB contains a damaged or unreadable ZIP member",
            {"member": name, "reason": type(exc).__name__},
        )


def _reject_xml_declarations(payload: bytes, document_path: str) -> None:
    # Removing NUL bytes makes the ASCII tokens visible in UTF-16/UTF-32 documents as well.
    flattened = payload.replace(b"\x00", b"").upper()
    if b"<!ENTITY" in flattened:
        _invalid(
            "EPUB XML documents cannot contain ENTITY declarations",
            {"document_path": document_path},
        )
    doctype_positions = [match.start() for match in re.finditer(re.escape(b"<!DOCTYPE"), flattened)]
    doctype_matches = list(_SAFE_DOCTYPE_RE.finditer(flattened))
    if (
        len(doctype_positions) > 1
        or [match.start() for match in doctype_matches] != doctype_positions
    ):
        _invalid(
            "EPUB XML documents cannot contain internal or malformed DTD declarations",
            {"document_path": document_path},
        )


def _parse_xml(payload: bytes, document_path: str) -> ET.Element:
    _reject_xml_declarations(payload, document_path)
    try:
        # The archive/member bounds plus the declaration scanner above remove the XML attack
        # surfaces relevant to ElementTree while keeping this module dependency-free.
        parser = ET.XMLParser(  # noqa: S314
            target=ET.TreeBuilder(insert_comments=True, insert_pis=True)
        )
        return ET.fromstring(payload, parser=parser)  # noqa: S314
    except (ET.ParseError, LookupError, ValueError) as exc:
        _invalid(
            "EPUB contains malformed XML",
            {"document_path": document_path, "reason": type(exc).__name__},
        )


def _local_name(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].casefold()


def _elements(root: ET.Element, local_name: str) -> list[ET.Element]:
    expected = local_name.casefold()
    return [element for element in root.iter() if _local_name(element.tag) == expected]


def _first_child(root: ET.Element, local_name: str) -> ET.Element | None:
    expected = local_name.casefold()
    return next(
        (element for element in root.iter() if _local_name(element.tag) == expected),
        None,
    )


def _has_epub_toc_navigation(root: ET.Element) -> bool:
    attribute = f"{{{_EPUB_NAMESPACE}}}type"
    return any(
        _local_name(element.tag) == "nav"
        and "toc" in element.attrib.get(attribute, "").casefold().split()
        for element in root.iter()
    )


def _resolve_archive_reference(base_path: str, reference: str, context: str) -> str | None:
    value = reference.strip()
    if not value or value.startswith("#"):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        _invalid("EPUB contains an invalid resource reference", {"context": context})
    scheme = parsed.scheme.casefold()
    if scheme:
        if scheme in _EXTERNAL_SCHEMES:
            return None
        _invalid(
            "EPUB contains an unsupported resource-reference scheme",
            {"context": context, "scheme": scheme},
        )
    if parsed.netloc or parsed.query:
        _invalid("EPUB contains an invalid internal resource reference", {"context": context})
    try:
        decoded = unquote(parsed.path, errors="strict")
    except (UnicodeDecodeError, ValueError):
        _invalid("EPUB contains an invalid encoded resource reference", {"context": context})
    if not decoded:
        return None
    if "\\" in decoded or _contains_control_character(decoded) or decoded.startswith("/"):
        _unsafe_archive("EPUB contains an unsafe resource reference", {"context": context})
    raw_parts = PurePosixPath(decoded).parts
    if any(part == ".." for part in raw_parts):
        # Relative parent traversal is valid inside an EPUB only if it remains within the archive.
        combined = posixpath.normpath(posixpath.join(posixpath.dirname(base_path), decoded))
    else:
        combined = posixpath.normpath(posixpath.join(posixpath.dirname(base_path), decoded))
    if combined in {"", ".", ".."} or combined.startswith("../") or combined.startswith("/"):
        _unsafe_archive("EPUB resource reference escapes the archive", {"context": context})
    return combined


def _require_reference(
    members: Mapping[str, zipfile.ZipInfo], base_path: str, reference: str, context: str
) -> str | None:
    target = _resolve_archive_reference(base_path, reference, context)
    if target is not None and (target not in members or members[target].is_dir()):
        _invalid(
            "EPUB references a missing internal resource",
            {"context": context, "target": target},
        )
    return target


def _element_indexes(root: ET.Element) -> tuple[dict[ET.Element, int], dict[int, ET.Element]]:
    elements = [element for element in root.iter() if isinstance(element.tag, str)]
    return (
        {element: index for index, element in enumerate(elements)},
        {index: element for index, element in enumerate(elements)},
    )


def _visible_core(value: str | None) -> str | None:
    if value is None:
        return None
    match = _LEADING_TRAILING_RE.match(value)
    if match is None or not match.group(2):
        return None
    return match.group(2)


def _locator_key(locator: Mapping[str, Any]) -> str:
    return json.dumps(dict(locator), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _split_text_parts(source_text: str) -> list[tuple[str, str]]:
    """Split a slot core deterministically while retaining exact inter-part separators."""

    if len(source_text) <= _MAX_TEXT_UNIT_CHARS:
        return [(source_text, "")]
    parts: list[tuple[str, str]] = []
    cursor = 0
    minimum_soft_break = _MAX_TEXT_UNIT_CHARS // 2
    while len(source_text) - cursor > _MAX_TEXT_UNIT_CHARS:
        limit = cursor + _MAX_TEXT_UNIT_CHARS
        boundary: int | None = None

        for index in range(limit - 1, cursor + minimum_soft_break - 1, -1):
            if source_text[index] in _SENTENCE_ENDINGS:
                boundary = index + 1
                break
        if boundary is None:
            window = source_text[cursor:limit]
            whitespace_matches = list(re.finditer(r"\s+", window))
            candidate = next(
                (
                    match
                    for match in reversed(whitespace_matches)
                    if match.start() >= minimum_soft_break
                ),
                None,
            )
            if candidate is not None:
                boundary = cursor + candidate.start()
        if boundary is None or boundary <= cursor:
            boundary = limit

        joiner_end = boundary
        while joiner_end < len(source_text) and source_text[joiner_end].isspace():
            joiner_end += 1
        part = source_text[cursor:boundary]
        if not part:
            boundary = limit
            joiner_end = boundary
            part = source_text[cursor:boundary]
        parts.append((part, source_text[boundary:joiner_end]))
        cursor = joiner_end
    parts.append((source_text[cursor:], ""))
    if any(not part or len(part) > _MAX_TEXT_UNIT_CHARS for part, _ in parts):
        _invalid("EPUB visible-text splitting produced an invalid part")
    if "".join(part + joiner for part, joiner in parts) != source_text:
        _invalid("EPUB visible-text splitting could not preserve source content")
    return parts


def _make_units(
    *,
    source_text: str,
    document_path: str,
    element_index: int,
    slot: str,
    attribute: str | None,
    document_order: int,
    document_type: str,
) -> list[dict[str, Any]]:
    parts = _split_text_parts(source_text)
    units: list[dict[str, Any]] = []
    for part_index, (part, joiner) in enumerate(parts):
        locator = {
            "document_path": document_path,
            "element_index": element_index,
            "slot": slot,
            "attribute": attribute,
            "part_index": part_index,
            "part_count": len(parts),
            "document_order": document_order,
            "document_type": document_type,
        }
        units.append(
            {
                "source_text": part,
                "joiner": joiner,
                "locator": locator,
                "locator_key": _locator_key(locator),
            }
        )
    return units


def _extract_opf_units(
    root: ET.Element, document_path: str, document_order: int
) -> list[dict[str, Any]]:
    indexes, _ = _element_indexes(root)
    metadata = _first_child(root, "metadata")
    if metadata is None:
        return []
    units: list[dict[str, Any]] = []
    for element in metadata.iter():
        if _local_name(element.tag) not in {"title", "description", "subject"}:
            continue
        source_text = _visible_core(element.text)
        if source_text is not None:
            units.extend(
                _make_units(
                    source_text=source_text,
                    document_path=document_path,
                    element_index=indexes[element],
                    slot="text",
                    attribute=None,
                    document_order=document_order,
                    document_type="opf_metadata",
                )
            )
    return units


def _extract_xhtml_units(
    root: ET.Element,
    document_path: str,
    document_order: int,
    document_type: str,
) -> list[dict[str, Any]]:
    indexes, _ = _element_indexes(root)
    body_roots = _elements(root, "body")
    roots = body_roots if body_roots else _elements(root, "nav")
    units: list[dict[str, Any]] = []

    def add_value(
        element: ET.Element, value: str | None, slot: str, attribute: str | None = None
    ) -> None:
        source_text = _visible_core(value)
        if source_text is None:
            return
        units.extend(
            _make_units(
                source_text=source_text,
                document_path=document_path,
                element_index=indexes[element],
                slot=slot,
                attribute=attribute,
                document_order=document_order,
                document_type=document_type,
            )
        )

    def walk(element: ET.Element, blocked: bool = False) -> None:
        name = _local_name(element.tag)
        current_blocked = blocked or name in _SKIPPED_ELEMENTS
        if not current_blocked:
            if name == "img":
                for attribute in ("alt", "title"):
                    add_value(element, element.attrib.get(attribute), "attribute", attribute)
            add_value(element, element.text, "text")
            for child in list(element):
                walk(child, current_blocked)
                # A skipped child's tail is still visible in its non-skipped parent.
                add_value(child, child.tail, "tail")

    for body in roots:
        walk(body)
    return units


def _extract_ncx_units(
    root: ET.Element, document_path: str, document_order: int
) -> list[dict[str, Any]]:
    indexes, _ = _element_indexes(root)
    units: list[dict[str, Any]] = []
    for element in root.iter():
        if _local_name(element.tag) != "text":
            continue
        source_text = _visible_core(element.text)
        if source_text is not None:
            units.extend(
                _make_units(
                    source_text=source_text,
                    document_path=document_path,
                    element_index=indexes[element],
                    slot="text",
                    attribute=None,
                    document_order=document_order,
                    document_type="ncx",
                )
            )
    return units


def _metadata_summary(root: ET.Element) -> dict[str, list[str]]:
    metadata = _first_child(root, "metadata")
    result: dict[str, list[str]] = {
        "titles": [],
        "descriptions": [],
        "languages": [],
        "identifiers": [],
        "creators": [],
        "subjects": [],
    }
    if metadata is None:
        return result
    key_by_name = {
        "title": "titles",
        "description": "descriptions",
        "language": "languages",
        "identifier": "identifiers",
        "creator": "creators",
        "subject": "subjects",
    }
    for element in metadata.iter():
        key = key_by_name.get(_local_name(element.tag))
        value = _visible_core(element.text)
        if key is not None and value is not None:
            result[key].append(value)
    return result


def _validate_document_references(
    root: ET.Element,
    document_path: str,
    members: Mapping[str, zipfile.ZipInfo],
) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        for attribute, value in element.attrib.items():
            attribute_name = _local_name(attribute)
            if attribute_name in _RESOURCE_ATTRIBUTES:
                target = _require_reference(
                    members,
                    document_path,
                    value,
                    f"{document_path}:{_local_name(element.tag)}@{attribute_name}",
                )
                if target is not None:
                    references.append({"reference": value, "target": target})
            elif attribute_name == "style":
                for match in _CSS_URL_RE.finditer(_CSS_COMMENT_RE.sub("", value)):
                    uri = match.group("uri")
                    target = _require_reference(
                        members, document_path, uri, f"{document_path}:style"
                    )
                    if target is not None:
                        references.append({"reference": uri, "target": target})
    return references


def _validate_css_references(
    payload: bytes,
    document_path: str,
    members: Mapping[str, zipfile.ZipInfo],
) -> list[dict[str, str]]:
    try:
        css = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        _invalid("EPUB CSS resource is not valid UTF-8", {"document_path": document_path})
    references: list[dict[str, str]] = []
    for match in _CSS_URL_RE.finditer(_CSS_COMMENT_RE.sub("", css)):
        uri = match.group("uri")
        target = _require_reference(members, document_path, uri, f"{document_path}:css")
        if target is not None:
            references.append({"reference": uri, "target": target})
    return references


def _archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(_READ_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        _invalid("EPUB source could not be read", {"reason": type(exc).__name__})
    return digest.hexdigest()


def inspect_epub(
    source_path: str | os.PathLike[str], settings: Settings | None = None
) -> dict[str, Any]:
    """Validate and inspect an unencrypted EPUB 2/3 into a JSON-serializable manifest.

    Visible text units are ordered as package metadata, spine documents, remaining XHTML
    documents, then NCX navigation.  Their locators are stable for the immutable source archive.
    """

    path = Path(source_path)
    try:
        archive = zipfile.ZipFile(path, "r")
    except (BadZipfileError, OSError, zipfile.LargeZipFile) as exc:
        _invalid("Source is not a valid EPUB ZIP archive", {"reason": type(exc).__name__})

    with archive:
        members, archive_summary = _validate_archive_entries(archive, settings)
        infos = archive.infolist()
        first = infos[0]
        if first.filename != _MIMETYPE_PATH:
            _invalid("EPUB mimetype must be the first ZIP member")
        if first.compress_type != zipfile.ZIP_STORED:
            _invalid("EPUB mimetype ZIP member must be stored without compression")
        if _read_member(archive, members, _MIMETYPE_PATH) != _EPUB_MIMETYPE:
            _invalid("EPUB mimetype content is invalid")

        container_payload = _read_member(archive, members, _CONTAINER_PATH)
        container_root = _parse_xml(container_payload, _CONTAINER_PATH)
        rootfiles = _elements(container_root, "rootfile")
        if not rootfiles:
            _invalid("EPUB container does not declare a package document")
        preferred = next(
            (
                element
                for element in rootfiles
                if element.attrib.get("media-type", "").casefold() == _PACKAGE_MEDIA_TYPE
            ),
            rootfiles[0],
        )
        package_reference = preferred.attrib.get("full-path", "")
        package_path = _resolve_archive_reference("", package_reference, _CONTAINER_PATH)
        if package_path is None or package_path not in members or members[package_path].is_dir():
            _invalid("EPUB package document referenced by container.xml is missing")

        package_payload = _read_member(archive, members, package_path)
        package_root = _parse_xml(package_payload, package_path)
        if _local_name(package_root.tag) != "package":
            _invalid("EPUB package document root must be an OPF package element")
        version = package_root.attrib.get("version", "").strip()
        if not (version.startswith("2") or version.startswith("3")):
            _unsupported_format("Only common EPUB 2 and EPUB 3 package versions are supported")

        manifest_element = _first_child(package_root, "manifest")
        spine_element = _first_child(package_root, "spine")
        if manifest_element is None or spine_element is None:
            _invalid("EPUB package document must contain manifest and spine elements")

        item_by_id: dict[str, dict[str, Any]] = {}
        item_paths: set[str] = set()
        manifest_items: list[dict[str, Any]] = []
        for item_element in list(manifest_element):
            if _local_name(item_element.tag) != "item":
                continue
            item_id = item_element.attrib.get("id", "").strip()
            href = item_element.attrib.get("href", "").strip()
            media_type = item_element.attrib.get("media-type", "").strip().casefold()
            if not item_id or not href or not media_type:
                _invalid("Every EPUB manifest item requires id, href, and media-type")
            if item_id in item_by_id:
                _invalid("EPUB manifest contains a duplicate item id", {"item_id": item_id})
            item_path = _require_reference(
                members, package_path, href, f"{package_path}:manifest[{item_id}]"
            )
            if item_path is None:
                _invalid("EPUB manifest item href cannot be fragment-only", {"item_id": item_id})
            if item_path in item_paths:
                _invalid("EPUB manifest contains duplicate resource paths", {"path": item_path})
            item_paths.add(item_path)
            properties = sorted(set(item_element.attrib.get("properties", "").split()))
            public_item = {
                "id": item_id,
                "href": href,
                "path": item_path,
                "media_type": media_type,
                "properties": properties,
                "fallback": item_element.attrib.get("fallback"),
                "media_overlay": item_element.attrib.get("media-overlay"),
            }
            item_by_id[item_id] = public_item
            manifest_items.append(public_item)
        if not manifest_items:
            _invalid("EPUB manifest is empty")
        for manifest_item in manifest_items:
            for field_name in ("fallback", "media_overlay"):
                referenced_id = manifest_item[field_name]
                if referenced_id is not None and referenced_id not in item_by_id:
                    _invalid(
                        "EPUB manifest item references an unknown fallback or media overlay",
                        {
                            "item_id": manifest_item["id"],
                            "field": field_name,
                            "referenced_id": referenced_id,
                        },
                    )

        spine: list[dict[str, Any]] = []
        spine_paths: list[str] = []
        for itemref in list(spine_element):
            if _local_name(itemref.tag) != "itemref":
                continue
            idref = itemref.attrib.get("idref", "").strip()
            spine_item = item_by_id.get(idref)
            if spine_item is None:
                _invalid("EPUB spine references a missing manifest item", {"idref": idref})
            if spine_item["media_type"] not in _XHTML_MEDIA_TYPES:
                _invalid(
                    "EPUB spine item is not a supported XHTML document",
                    {"idref": idref, "media_type": spine_item["media_type"]},
                )
            entry = {
                "idref": idref,
                "path": spine_item["path"],
                "media_type": spine_item["media_type"],
                "linear": itemref.attrib.get("linear", "yes").casefold() != "no",
            }
            spine.append(entry)
            spine_paths.append(cast(str, spine_item["path"]))
        if not spine:
            _invalid("EPUB spine is empty")

        nav_items = [
            manifest_item
            for manifest_item in manifest_items
            if "nav" in manifest_item["properties"]
        ]
        ncx_items = [
            manifest_item
            for manifest_item in manifest_items
            if manifest_item["media_type"] == _NCX_MEDIA_TYPE
        ]
        if version.startswith("3"):
            if len(nav_items) != 1:
                _invalid("EPUB 3 package must declare exactly one navigation document")
            if nav_items[0]["media_type"] != "application/xhtml+xml":
                _invalid("EPUB 3 navigation document must use application/xhtml+xml")
        if version.startswith("2"):
            toc_id = spine_element.attrib.get("toc", "").strip()
            if not toc_id or toc_id not in item_by_id:
                _invalid("EPUB 2 spine is missing a valid NCX toc reference")
            if item_by_id[toc_id]["media_type"] != _NCX_MEDIA_TYPE:
                _invalid("EPUB 2 spine toc reference is not an NCX document")

        cover_path: str | None = next(
            (
                cast(str, manifest_item["path"])
                for manifest_item in manifest_items
                if "cover-image" in manifest_item["properties"]
            ),
            None,
        )
        if cover_path is None:
            metadata_element = _first_child(package_root, "metadata")
            if metadata_element is not None:
                cover_id = next(
                    (
                        element.attrib.get("content", "")
                        for element in metadata_element.iter()
                        if _local_name(element.tag) == "meta"
                        and element.attrib.get("name", "").casefold() == "cover"
                    ),
                    "",
                )
                cover_item = item_by_id.get(cover_id)
                if cover_item is not None:
                    cover_path = cast(str, cover_item["path"])

        text_units = _extract_opf_units(package_root, package_path, 0)
        documents: list[dict[str, Any]] = []
        references = _validate_document_references(package_root, package_path, members)
        parsed_documents: dict[str, ET.Element] = {package_path: package_root}

        ordered_xhtml_paths = list(dict.fromkeys(spine_paths))
        ordered_xhtml_paths.extend(
            cast(str, manifest_item["path"])
            for manifest_item in manifest_items
            if manifest_item["media_type"] in _XHTML_MEDIA_TYPES
            and manifest_item["path"] not in ordered_xhtml_paths
        )
        item_by_path = {
            cast(str, manifest_item["path"]): manifest_item for manifest_item in manifest_items
        }
        document_order = 1
        for document_path in ordered_xhtml_paths:
            document_item = item_by_path[document_path]
            root = _parse_xml(_read_member(archive, members, document_path), document_path)
            if _local_name(root.tag) not in {"html", "xhtml"}:
                _invalid(
                    "EPUB XHTML resource has an unexpected root element",
                    {"document_path": document_path},
                )
            parsed_documents[document_path] = root
            document_type = "nav" if "nav" in document_item["properties"] else "xhtml"
            if (
                version.startswith("3")
                and document_type == "nav"
                and not _has_epub_toc_navigation(root)
            ):
                _invalid(
                    "EPUB 3 navigation document must contain nav with epub:type toc",
                    {"document_path": document_path},
                )
            units = _extract_xhtml_units(root, document_path, document_order, document_type)
            start = len(text_units)
            text_units.extend(units)
            references.extend(_validate_document_references(root, document_path, members))
            documents.append(
                {
                    "path": document_path,
                    "manifest_id": document_item["id"],
                    "media_type": document_item["media_type"],
                    "document_type": document_type,
                    "document_order": document_order,
                    "text_unit_start": start,
                    "text_unit_count": len(units),
                }
            )
            document_order += 1

        for ncx_item in ncx_items:
            document_path = cast(str, ncx_item["path"])
            root = _parse_xml(_read_member(archive, members, document_path), document_path)
            if _local_name(root.tag) != "ncx":
                _invalid("EPUB NCX resource has an unexpected root element")
            parsed_documents[document_path] = root
            units = _extract_ncx_units(root, document_path, document_order)
            start = len(text_units)
            text_units.extend(units)
            references.extend(_validate_document_references(root, document_path, members))
            documents.append(
                {
                    "path": document_path,
                    "manifest_id": ncx_item["id"],
                    "media_type": ncx_item["media_type"],
                    "document_type": "ncx",
                    "document_order": document_order,
                    "text_unit_start": start,
                    "text_unit_count": len(units),
                }
            )
            document_order += 1

        for manifest_item in manifest_items:
            item_path = cast(str, manifest_item["path"])
            media_type = cast(str, manifest_item["media_type"])
            if media_type == "text/css":
                references.extend(
                    _validate_css_references(
                        _read_member(archive, members, item_path), item_path, members
                    )
                )
            elif (
                media_type in _XML_MEDIA_TYPES or media_type.endswith("+xml")
            ) and item_path not in parsed_documents:
                root = _parse_xml(_read_member(archive, members, item_path), item_path)
                references.extend(_validate_document_references(root, item_path, members))

        for sequence, unit in enumerate(text_units):
            unit["sequence"] = sequence

        entry_manifest = [
            {
                "path": info.filename,
                "size": info.file_size,
                "compressed_size": info.compress_size,
                "compression": (
                    "stored" if info.compress_type == zipfile.ZIP_STORED else "deflated"
                ),
                "crc32": f"{info.CRC:08x}",
                "directory": info.is_dir(),
            }
            for info in infos
        ]

    return {
        "inspection_version": 1,
        "format": "epub",
        "epub_version": version,
        "archive_sha256": _archive_sha256(path),
        "package_document": package_path,
        "metadata": _metadata_summary(package_root),
        "cover_path": cover_path,
        "manifest_items": manifest_items,
        "spine": spine,
        "reading_order": spine_paths,
        "navigation_documents": [cast(str, item["path"]) for item in [*nav_items, *ncx_items]],
        "documents": documents,
        "resource_references": references,
        "entries": entry_manifest,
        "text_units": text_units,
        "processing_rules": {
            "version": 1,
            "order": "OPF metadata, spine order, remaining XHTML manifest order, then NCX",
            "included": [
                "visible XHTML body/nav text",
                "NCX navLabel and title text",
                "img alt and title attributes",
                "OPF title, description, and subject metadata (creator is display-only)",
            ],
            "excluded_elements": sorted(_SKIPPED_ELEMENTS),
            "ruby": "ruby base text is translated; rt and rp pronunciation/fallback text is kept",
            "links": (
                "URLs, paths, anchors, element names, and non-image attributes are never translated"
            ),
            "whitespace": "leading and trailing whitespace in every XML slot is preserved",
            "splitting": (
                "each XML slot is deterministically split at sentence/whitespace boundaries "
                "to at most 1800 source characters; joiner stores the exact separator after a part"
            ),
            "missing_translation": (
                "missing, failed, non-string, or blank translations keep source text"
            ),
            "language": (
                "existing dc:language values are set to the export target; one is added if "
                "absent; XHTML and nav html roots receive matching lang and xml:lang"
            ),
        },
        "validation": {
            "valid": True,
            "package_document": package_path,
            "spine_document_count": len(spine),
            "document_count": len(documents),
            "resource_count": len(manifest_items),
            "text_unit_count": len(text_units),
            **archive_summary,
        },
    }


def validate_epub(
    source_path: str | os.PathLike[str], settings: Settings | None = None
) -> dict[str, Any]:
    """Perform a fresh validation pass and return its compact JSON-safe summary."""

    inspection = inspect_epub(source_path, settings)
    return cast(dict[str, Any], inspection["validation"])


def _normalize_translation(value: object) -> str | None:
    if isinstance(value, Mapping):
        status = value.get("status")
        if status is not None and str(status).casefold() not in {"succeeded", "success", "ok"}:
            return None
        for key in ("translated_text", "translation", "target_text", "text"):
            if key in value:
                return _normalize_translation(value[key])
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _translation_values(
    units: Sequence[Mapping[str, Any]],
    translations: Mapping[object, object] | Sequence[object],
) -> dict[int, str]:
    result: dict[int, str] = {}
    if isinstance(translations, Mapping):
        nested = translations.get("translations")
        if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes, bytearray)):
            return _translation_values(units, nested)
        for unit in units:
            sequence = int(unit["sequence"])
            locator = cast(Mapping[str, Any], unit["locator"])
            locator_key = str(unit["locator_key"])
            tuple_key = tuple(locator.get(key) for key in locator)
            candidates: tuple[object, ...] = (sequence, str(sequence), locator_key, tuple_key)
            for candidate in candidates:
                if candidate in translations:
                    translated = _normalize_translation(translations[candidate])
                    if translated is not None:
                        result[sequence] = translated
                    break
        return result

    if isinstance(translations, (str, bytes, bytearray)):
        return result
    records = list(translations)
    if records and all(isinstance(record, Mapping) for record in records):
        sequence_by_locator = {str(unit["locator_key"]): int(unit["sequence"]) for unit in units}
        for fallback_sequence, record_object in enumerate(records):
            record = cast(Mapping[object, object], record_object)
            sequence_value = record.get("sequence")
            if sequence_value is None and isinstance(record.get("locator"), Mapping):
                locator = cast(Mapping[str, Any], record["locator"])
                sequence_value = sequence_by_locator.get(_locator_key(locator))
            if sequence_value is None:
                sequence = fallback_sequence
            elif isinstance(sequence_value, (int, str)):
                try:
                    sequence = int(sequence_value)
                except ValueError:
                    continue
            else:
                continue
            translated = _normalize_translation(record)
            if translated is not None and 0 <= sequence < len(units):
                result[sequence] = translated
        return result

    for sequence, value in enumerate(records[: len(units)]):
        translated = _normalize_translation(value)
        if translated is not None:
            result[sequence] = translated
    return result


def _replace_visible_core(original: str, translated: str) -> str:
    match = _LEADING_TRAILING_RE.match(original)
    if match is None:
        return translated
    return f"{match.group(1)}{translated}{match.group(3)}"


def _apply_document_translations(
    payload: bytes,
    document_path: str,
    units: Sequence[Mapping[str, Any]],
    translated_by_sequence: Mapping[int, str],
    *,
    target_language: str | None = None,
) -> tuple[bytes, int, bool]:
    root = _parse_xml(payload, document_path)
    _, by_index = _element_indexes(root)
    applied = 0
    changed = False
    grouped: dict[tuple[int, str, str | None], list[Mapping[str, Any]]] = {}
    for unit in units:
        locator = cast(Mapping[str, Any], unit["locator"])
        attribute_value = locator.get("attribute")
        attribute = attribute_value if isinstance(attribute_value, str) else None
        group_key = (int(locator["element_index"]), str(locator["slot"]), attribute)
        grouped.setdefault(group_key, []).append(unit)

    for (element_index, slot, attribute), slot_units in grouped.items():
        ordered_units = sorted(
            slot_units,
            key=lambda item: int(cast(Mapping[str, Any], item["locator"])["part_index"]),
        )
        expected_part_count = int(
            cast(Mapping[str, Any], ordered_units[0]["locator"])["part_count"]
        )
        indexes = [
            int(cast(Mapping[str, Any], unit["locator"])["part_index"]) for unit in ordered_units
        ]
        if expected_part_count != len(ordered_units) or indexes != list(range(len(ordered_units))):
            _invalid("EPUB text locator parts are incomplete or out of order")
        successful_in_slot = sum(
            int(int(unit["sequence"]) in translated_by_sequence) for unit in ordered_units
        )
        if successful_in_slot == 0:
            continue
        try:
            element = by_index[element_index]
        except (KeyError, TypeError, ValueError):
            _invalid("EPUB text locator no longer matches its source document")
        source_core = "".join(
            str(unit["source_text"]) + str(unit.get("joiner", "")) for unit in ordered_units
        )
        rebuilt_core = "".join(
            translated_by_sequence.get(int(unit["sequence"]), str(unit["source_text"]))
            + str(unit.get("joiner", ""))
            for unit in ordered_units
        )
        if slot == "text":
            original = element.text
            if original is None:
                _invalid("EPUB text locator points to a missing text slot")
            if _visible_core(original) != source_core:
                _invalid("EPUB text locator source no longer matches its XML slot")
            replacement = _replace_visible_core(original, rebuilt_core)
            if replacement != original:
                element.text = replacement
                changed = True
        elif slot == "tail":
            original = element.tail
            if original is None:
                _invalid("EPUB text locator points to a missing tail slot")
            if _visible_core(original) != source_core:
                _invalid("EPUB text locator source no longer matches its XML slot")
            replacement = _replace_visible_core(original, rebuilt_core)
            if replacement != original:
                element.tail = replacement
                changed = True
        elif slot == "attribute" and isinstance(attribute, str):
            original = element.attrib.get(attribute)
            if original is None:
                _invalid("EPUB text locator points to a missing attribute")
            if _visible_core(original) != source_core:
                _invalid("EPUB text locator source no longer matches its XML slot")
            replacement = _replace_visible_core(original, rebuilt_core)
            if replacement != original:
                element.attrib[attribute] = replacement
                changed = True
        else:
            _invalid("EPUB text locator contains an unsupported slot")
        applied += successful_in_slot

    if target_language is not None:
        root_name = _local_name(root.tag)
        if root_name == "package":
            metadata = _first_child(root, "metadata")
            if metadata is None:
                _invalid("EPUB package document has no metadata element")
            language_elements = [
                element for element in metadata.iter() if _local_name(element.tag) == "language"
            ]
            if language_elements:
                for element in language_elements:
                    if element.text != target_language:
                        element.text = target_language
                        changed = True
            else:
                ET.SubElement(metadata, f"{{{_DC_NAMESPACE}}}language").text = target_language
                changed = True
        elif root_name in {"html", "xhtml"}:
            for attribute in ("lang", "{http://www.w3.org/XML/1998/namespace}lang"):
                if root.attrib.get(attribute) != target_language:
                    root.attrib[attribute] = target_language
                    changed = True

    if not changed:
        return payload, applied, False
    for prefix, namespace in _KNOWN_NAMESPACES.items():
        ET.register_namespace(prefix, namespace)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), applied, True


def _clone_zip_info(source: zipfile.ZipInfo, *, stored: bool = False) -> zipfile.ZipInfo:
    clone = zipfile.ZipInfo(source.filename, date_time=source.date_time)
    clone.compress_type = zipfile.ZIP_STORED if stored else source.compress_type
    clone.comment = source.comment
    clone.extra = source.extra
    clone.create_system = source.create_system
    clone.create_version = source.create_version
    clone.extract_version = source.extract_version
    clone.internal_attr = source.internal_attr
    clone.external_attr = source.external_attr
    clone.volume = source.volume
    return clone


def _verify_unchanged_payloads(
    source_path: Path, output_path: Path, modified_paths: set[str]
) -> int:
    verified = 0
    try:
        with (
            zipfile.ZipFile(source_path, "r") as source,
            zipfile.ZipFile(output_path, "r") as output,
        ):
            for info in source.infolist():
                if info.is_dir() or info.filename in modified_paths:
                    continue
                if source.read(info) != output.read(info.filename):
                    _invalid(
                        "EPUB export changed a non-text resource",
                        {"member": info.filename},
                    )
                verified += 1
    except LinguaError:
        raise
    except (BadZipfileError, KeyError, OSError, RuntimeError) as exc:
        _invalid(
            "EPUB export could not be compared with its source",
            {"reason": type(exc).__name__},
        )
    return verified


def _assert_manifest_matches(
    supplied: Mapping[str, Any], inspected: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    supplied_units_object = supplied.get("text_units")
    inspected_units_object = inspected.get("text_units")
    if not isinstance(supplied_units_object, list) or not isinstance(inspected_units_object, list):
        _invalid("EPUB inspection manifest does not contain text units")
    supplied_units = cast(list[Mapping[str, Any]], supplied_units_object)
    inspected_units = cast(list[Mapping[str, Any]], inspected_units_object)
    if supplied.get("archive_sha256") != inspected.get("archive_sha256"):
        _invalid("EPUB inspection manifest belongs to a different source archive")
    supplied_identity = [
        (
            unit.get("sequence"),
            unit.get("locator_key"),
            unit.get("source_text"),
            unit.get("joiner"),
        )
        for unit in supplied_units
    ]
    inspected_identity = [
        (
            unit.get("sequence"),
            unit.get("locator_key"),
            unit.get("source_text"),
            unit.get("joiner"),
        )
        for unit in inspected_units
    ]
    if supplied_identity != inspected_identity:
        _invalid("EPUB inspection manifest text locators do not match the source archive")
    return inspected_units


def is_bcp47_language_tag(value: str) -> bool:
    """Validate the common structural subset of BCP 47 without a registry dependency."""

    if not value or len(value) > 255:
        return False
    subtags = value.split("-")
    if any(
        not subtag or len(subtag) > 8 or not subtag.isascii() or not subtag.isalnum()
        for subtag in subtags
    ):
        return False
    if subtags[0].casefold() == "x":
        return len(subtags) > 1
    if not (2 <= len(subtags[0]) <= 3 and subtags[0].isalpha()):
        return False

    index = 1
    extlang_count = 0
    while (
        index < len(subtags)
        and len(subtags[index]) == 3
        and subtags[index].isalpha()
        and extlang_count < 3
    ):
        index += 1
        extlang_count += 1
    if index < len(subtags) and len(subtags[index]) == 4 and subtags[index].isalpha():
        index += 1
    if index < len(subtags) and (
        (len(subtags[index]) == 2 and subtags[index].isalpha())
        or (len(subtags[index]) == 3 and subtags[index].isdigit())
    ):
        index += 1
    while index < len(subtags) and (
        5 <= len(subtags[index]) <= 8 or (len(subtags[index]) == 4 and subtags[index][0].isdigit())
    ):
        index += 1

    extension_singletons: set[str] = set()
    while index < len(subtags) and len(subtags[index]) == 1 and subtags[index].casefold() != "x":
        singleton = subtags[index].casefold()
        if singleton in extension_singletons:
            return False
        extension_singletons.add(singleton)
        index += 1
        extension_start = index
        while index < len(subtags) and 2 <= len(subtags[index]) <= 8:
            index += 1
        if index == extension_start:
            return False

    if index < len(subtags) and subtags[index].casefold() == "x":
        index += 1
        private_start = index
        while index < len(subtags) and 1 <= len(subtags[index]) <= 8:
            index += 1
        if index == private_start:
            return False
    return index == len(subtags)


def build_translated_epub(
    source_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    manifest: Mapping[str, Any],
    translations: Mapping[object, object] | Sequence[object],
    target_language: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Atomically rebuild an EPUB, applying translations by sequence or locator.

    Missing, failed, blank, and malformed translation values leave the original text untouched.
    All non-text ZIP payload bytes are compared after the build.  The temporary result is then
    independently validated and re-inspected before it replaces ``output_path``.
    """

    source = Path(source_path)
    output = Path(output_path)
    if source.resolve() == output.resolve():
        _invalid("Translated EPUB output must not overwrite the immutable source")
    language = target_language.strip()
    if not is_bcp47_language_tag(language):
        _invalid("Target language must be a plausible BCP 47 language tag")

    inspected = inspect_epub(source, settings)
    units = _assert_manifest_matches(manifest, inspected)
    translated_by_sequence = _translation_values(units, translations)
    package_path = str(inspected["package_document"])
    language_document_paths = {
        str(document["path"])
        for document in cast(Sequence[Mapping[str, Any]], inspected["documents"])
        if document.get("document_type") in {"xhtml", "nav"}
    }
    language_document_paths.add(package_path)
    units_by_document: dict[str, list[Mapping[str, Any]]] = {}
    for unit in units:
        locator = cast(Mapping[str, Any], unit["locator"])
        units_by_document.setdefault(str(locator["document_path"]), []).append(unit)

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
        )
        temporary_path = Path(temporary.name)
        temporary.close()
    except OSError as exc:
        raise LinguaError(
            _error_code("STORAGE", ErrorCode.STORAGE),
            "Translated EPUB output could not be prepared",
            {"reason": type(exc).__name__},
        ) from exc

    modified_paths: set[str] = set()
    applied = 0
    try:
        with (
            zipfile.ZipFile(source, "r") as source_archive,
            zipfile.ZipFile(temporary_path, "w", allowZip64=True) as output_archive,
        ):
            output_archive.comment = source_archive.comment
            for index, member in enumerate(source_archive.infolist()):
                payload = source_archive.read(member)
                document_units = units_by_document.get(member.filename, [])
                target = language if member.filename in language_document_paths else None
                if document_units or target is not None:
                    payload, document_applied, changed = _apply_document_translations(
                        payload,
                        member.filename,
                        document_units,
                        translated_by_sequence,
                        target_language=target,
                    )
                    applied += document_applied
                    if changed:
                        modified_paths.add(member.filename)
                clone = _clone_zip_info(
                    member,
                    stored=index == 0 and member.filename == _MIMETYPE_PATH,
                )
                output_archive.writestr(clone, payload)

        try:
            verified_non_text = _verify_unchanged_payloads(source, temporary_path, modified_paths)
            validation = validate_epub(temporary_path, settings)
            reinspection = inspect_epub(temporary_path, settings)
        except LinguaError as exc:
            _validation_failed({"cause_code": exc.code})
        output_sha256 = str(reinspection["archive_sha256"])
        os.replace(temporary_path, output)
    except LinguaError:
        temporary_path.unlink(missing_ok=True)
        raise
    except (BadZipfileError, KeyError, OSError, RuntimeError, ValueError) as exc:
        temporary_path.unlink(missing_ok=True)
        raise LinguaError(
            _error_code("STORAGE", ErrorCode.STORAGE),
            "Translated EPUB could not be built atomically",
            {"reason": type(exc).__name__},
        ) from exc

    return {
        "valid": True,
        "output_sha256": output_sha256,
        "target_language": language,
        "text_unit_count": len(units),
        "translated_unit_count": applied,
        "preserved_unit_count": len(units) - applied,
        "modified_documents": sorted(modified_paths),
        "unchanged_payloads_verified": verified_non_text,
        "validation": validation,
        "reinspection": {
            "epub_version": reinspection["epub_version"],
            "package_document": reinspection["package_document"],
            "reading_order": reinspection["reading_order"],
            "resource_count": reinspection["validation"]["resource_count"],
            "document_count": reinspection["validation"]["document_count"],
            "text_unit_count": reinspection["validation"]["text_unit_count"],
            "languages": reinspection["metadata"]["languages"],
        },
    }


__all__ = [
    "build_translated_epub",
    "inspect_epub",
    "is_bcp47_language_tag",
    "validate_epub",
]
