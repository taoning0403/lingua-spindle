from __future__ import annotations

import json
import struct
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

import linguaspindle.epub as epub_module
from linguaspindle.epub import build_translated_epub, inspect_epub, validate_epub
from linguaspindle.errors import ErrorCode, LinguaError


def _write_epub(
    path: Path,
    *,
    extra_members: list[tuple[str, bytes]] | None = None,
    encryption_xml: bool = False,
    unsafe_member: str | None = None,
    duplicate_member: bool = False,
    malformed_chapter: bool = False,
    long_paragraph: str | None = None,
    epub_version: str = "3.0",
    malicious_xml: bool = False,
) -> dict[str, bytes]:
    container = b"""<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
    package = b"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         unique-identifier="book-id" version="3.0">
  <metadata>
    <dc:identifier id="book-id">urn:uuid:test-book</dc:identifier>
    <dc:title>Spindle Book</dc:title>
    <dc:creator>Example Author</dc:creator>
    <dc:subject>Adventure</dc:subject>
    <dc:description>A compact fixture.</dc:description>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter-1" href="Text/chapter-1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter-2" href="Text/chapter-2.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="Text/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="cover" href="Images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>
    <item id="css" href="Styles/book.css" media-type="text/css"/>
    <item id="font" href="Fonts/book.woff2" media-type="font/woff2"/>
  </manifest>
  <spine>
    <itemref idref="chapter-1"/>
    <itemref idref="chapter-2"/>
  </spine>
</package>"""
    if epub_version == "2.0":
        package = package.replace(b'version="3.0"', b'version="2.0"')
        package = package.replace(b"<spine>", b'<spine toc="ncx">')
        package = package.replace(b' properties="nav"', b"")
    if malicious_xml:
        package = package.replace(
            b"</manifest>",
            b'<item id="evil" href="unused.xml" media-type="application/xml"/></manifest>',
        )
    chapter_1 = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Structural head title</title>
    <link rel="stylesheet" href="../Styles/book.css"/></head>
  <body>
    <h1>Chapter One</h1>
    <p>Hello <em>world</em>.</p>
    <p><a href="chapter-2.xhtml#note">Next chapter</a>
      <img src="../Images/cover.jpg" alt="Cover art" title="Front cover"/></p>
    <p><ruby>base<rt>pronunciation</rt><rp>(</rp></ruby></p>
    <code>code must stay</code><span>Visible after code</span>
    <script>script must stay</script>
    <svg xmlns="http://www.w3.org/2000/svg"><text>svg must stay</text></svg>
  </body>
</html>"""
    if malformed_chapter:
        chapter_1 = b"<html><body><p>broken"
    elif long_paragraph is not None:
        chapter_1 = chapter_1.replace(
            b"</body>",
            f'<p id="long-slot">{long_paragraph}</p></body>'.encode(),
        )
    chapter_2 = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Second structural title</title>
    <link rel="stylesheet" href="../Styles/book.css"/></head>
  <body><h1>Chapter Two</h1><p id="note">Footnote text</p>
  <a href="chapter-1.xhtml">Back</a></body>
</html>"""
    nav = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title>Navigation</title></head>
  <body><nav epub:type="toc"><ol>
    <li><a href="chapter-1.xhtml">Chapter One</a></li>
    <li><a href="chapter-2.xhtml">Chapter Two</a></li>
  </ol></nav></body>
</html>"""
    ncx = b"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <docTitle><text>Spindle Book</text></docTitle>
  <navMap>
    <navPoint id="one" playOrder="1"><navLabel><text>Chapter One</text></navLabel>
      <content src="Text/chapter-1.xhtml"/></navPoint>
    <navPoint id="two" playOrder="2"><navLabel><text>Chapter Two</text></navLabel>
      <content src="Text/chapter-2.xhtml#note"/></navPoint>
  </navMap>
</ncx>"""
    resources = {
        "mimetype": b"application/epub+zip",
        "META-INF/container.xml": container,
        "OEBPS/content.opf": package,
        "OEBPS/Text/chapter-1.xhtml": chapter_1,
        "OEBPS/Text/chapter-2.xhtml": chapter_2,
        "OEBPS/Text/nav.xhtml": nav,
        "OEBPS/toc.ncx": ncx,
        "OEBPS/Images/cover.jpg": b"\xff\xd8fixture-cover\xff\xd9",
        "OEBPS/Styles/book.css": (
            b"@font-face{font-family:Fixture;src:url('../Fonts/book.woff2')}"
            b"body{background:url('../Images/cover.jpg')}"
        ),
        "OEBPS/Fonts/book.woff2": b"wOF2fixture-font",
    }
    if malicious_xml:
        resources["OEBPS/unused.xml"] = b"<!DOCTYPE x [<!ENTITY y 'boom'>]><x>&y;</x>"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", resources["mimetype"], compress_type=zipfile.ZIP_STORED)
        for name, payload in resources.items():
            if name != "mimetype":
                archive.writestr(name, payload)
        if encryption_xml:
            archive.writestr("META-INF/encryption.xml", b"<encryption/>")
        if unsafe_member is not None:
            archive.writestr(unsafe_member, b"unsafe")
        for name, payload in extra_members or []:
            archive.writestr(name, payload)
        if duplicate_member:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr("OEBPS/Text/chapter-1.xhtml", chapter_1)
    return resources


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "max_archive_files": 2_000,
        "max_archive_uncompressed_bytes": 1_000 * 1024 * 1024,
        "max_archive_member_bytes": 100 * 1024 * 1024,
        "max_archive_compression_ratio": 100.0,
        "max_archive_path_depth": 20,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _assert_rejected(path: Path, settings: object | None = None) -> LinguaError:
    with pytest.raises(LinguaError) as caught:
        inspect_epub(path, settings)
    assert caught.value.code in {
        ErrorCode.INVALID_FORMAT,
        getattr(ErrorCode, "EPUB_INVALID", ErrorCode.INVALID_FORMAT),
        getattr(ErrorCode, "EPUB_PROTECTED", ErrorCode.INVALID_FORMAT),
        getattr(ErrorCode, "EPUB_UNSUPPORTED", ErrorCode.INVALID_FORMAT),
        getattr(ErrorCode, "ARCHIVE_UNSAFE", ErrorCode.INVALID_FORMAT),
        getattr(ErrorCode, "ARCHIVE_LIMIT_EXCEEDED", ErrorCode.INVALID_FORMAT),
        getattr(ErrorCode, "RESOURCE_LIMIT", ErrorCode.INVALID_FORMAT),
        getattr(ErrorCode, "UNSUPPORTED_PROTECTION", ErrorCode.INVALID_FORMAT),
    }
    return caught.value


def test_inspection_extracts_only_ordered_visible_text_and_is_json_safe(tmp_path: Path) -> None:
    source = tmp_path / "fixture.epub"
    _write_epub(source)

    manifest = inspect_epub(source, _settings())  # type: ignore[arg-type]

    json.dumps(manifest, ensure_ascii=False)
    assert manifest["epub_version"] == "3.0"
    assert manifest["package_document"] == "OEBPS/content.opf"
    assert manifest["reading_order"] == [
        "OEBPS/Text/chapter-1.xhtml",
        "OEBPS/Text/chapter-2.xhtml",
    ]
    assert manifest["cover_path"] == "OEBPS/Images/cover.jpg"
    texts = [unit["source_text"] for unit in manifest["text_units"]]
    assert texts[:3] == ["Spindle Book", "Adventure", "A compact fixture."]
    assert manifest["metadata"]["creators"] == ["Example Author"]
    assert manifest["metadata"]["subjects"] == ["Adventure"]
    assert "Example Author" not in texts
    assert "Chapter One" in texts
    assert "Chapter Two" in texts
    assert "Hello" in texts
    assert "world" in texts
    assert "Cover art" in texts
    assert "Front cover" in texts
    assert "base" in texts
    assert "Footnote text" in texts
    assert "Next chapter" in texts
    assert "Structural head title" not in texts
    assert "pronunciation" not in texts
    assert "code must stay" not in texts
    assert "script must stay" not in texts
    assert "svg must stay" not in texts
    assert [unit["sequence"] for unit in manifest["text_units"]] == list(range(len(texts)))
    assert all(
        set(unit["locator"])
        == {
            "document_path",
            "element_index",
            "slot",
            "attribute",
            "part_index",
            "part_count",
            "document_order",
            "document_type",
        }
        for unit in manifest["text_units"]
    )
    assert manifest["validation"]["valid"] is True
    assert manifest["processing_rules"]["ruby"].startswith("ruby base text")


def test_common_epub2_package_and_ncx_are_supported(tmp_path: Path) -> None:
    source = tmp_path / "fixture-v2.epub"
    _write_epub(source, epub_version="2.0")

    manifest = inspect_epub(source)

    assert manifest["epub_version"] == "2.0"
    assert "OEBPS/toc.ncx" in manifest["navigation_documents"]
    assert any(unit["locator"]["document_type"] == "ncx" for unit in manifest["text_units"])


def test_build_roundtrip_preserves_structure_links_and_non_text_payloads(tmp_path: Path) -> None:
    source = tmp_path / "source.epub"
    output = tmp_path / "translated.epub"
    original_resources = _write_epub(source)
    source_bytes = source.read_bytes()
    settings = _settings()
    manifest = inspect_epub(source, settings)  # type: ignore[arg-type]
    translations = [f"译:{unit['source_text']}" for unit in manifest["text_units"]]
    missing_sequence = next(
        unit["sequence"]
        for unit in manifest["text_units"]
        if unit["source_text"] == "Footnote text"
    )
    translations[missing_sequence] = ""

    summary = build_translated_epub(
        source,
        output,
        manifest,
        translations,
        "zh-Hans",
        settings,  # type: ignore[arg-type]
    )

    assert source.read_bytes() == source_bytes
    assert summary["valid"] is True
    assert summary["preserved_unit_count"] == 1
    assert validate_epub(output, settings)["valid"] is True  # type: ignore[arg-type]
    reimported = inspect_epub(output, settings)  # type: ignore[arg-type]
    translated_texts = [unit["source_text"] for unit in reimported["text_units"]]
    assert "译:Spindle Book" in translated_texts
    assert "译:Chapter One" in translated_texts
    assert "Footnote text" in translated_texts
    assert reimported["metadata"]["languages"] == ["zh-Hans"]
    assert reimported["reading_order"] == manifest["reading_order"]

    with zipfile.ZipFile(output) as archive:
        assert archive.infolist()[0].filename == "mimetype"
        assert archive.infolist()[0].compress_type == zipfile.ZIP_STORED
        assert (
            archive.read("OEBPS/Images/cover.jpg") == original_resources["OEBPS/Images/cover.jpg"]
        )
        assert archive.read("OEBPS/Styles/book.css") == original_resources["OEBPS/Styles/book.css"]
        assert (
            archive.read("OEBPS/Fonts/book.woff2") == original_resources["OEBPS/Fonts/book.woff2"]
        )
        chapter = archive.read("OEBPS/Text/chapter-1.xhtml").decode()
        assert 'href="chapter-2.xhtml#note"' in chapter
        assert 'src="../Images/cover.jpg"' in chapter
        chapter_root = ET.fromstring(chapter)  # noqa: S314 - generated fixture output
        assert chapter_root.attrib["lang"] == "zh-Hans"
        assert chapter_root.attrib["{http://www.w3.org/XML/1998/namespace}lang"] == "zh-Hans"
        nav_root = ET.fromstring(  # noqa: S314 - generated fixture output
            archive.read("OEBPS/Text/nav.xhtml")
        )
        assert nav_root.attrib["lang"] == "zh-Hans"
        assert nav_root.attrib["{http://www.w3.org/XML/1998/namespace}lang"] == "zh-Hans"


def test_translations_can_be_addressed_by_locator_and_failed_records_fall_back(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.epub"
    output = tmp_path / "translated.epub"
    _write_epub(source)
    manifest = inspect_epub(source)
    title = next(unit for unit in manifest["text_units"] if unit["source_text"] == "Spindle Book")
    chapter = next(unit for unit in manifest["text_units"] if unit["source_text"] == "Chapter One")
    translations = {
        title["locator_key"]: {"status": "succeeded", "translated_text": "线轴之书"},
        chapter["sequence"]: {"status": "failed", "translated_text": "must not be used"},
    }

    build_translated_epub(source, output, manifest, translations, "zh-CN")

    texts = [unit["source_text"] for unit in inspect_epub(output)["text_units"]]
    assert "线轴之书" in texts
    assert "Chapter One" in texts
    assert "must not be used" not in texts


def test_long_xml_slot_is_split_and_partial_translation_rebuilds_exactly(tmp_path: Path) -> None:
    source = tmp_path / "long.epub"
    output = tmp_path / "long-translated.epub"
    long_paragraph = " ".join(f"Sentence-{index}." for index in range(520))
    _write_epub(source, long_paragraph=long_paragraph)
    manifest = inspect_epub(source)
    parts = [
        unit
        for unit in manifest["text_units"]
        if unit["locator"]["document_path"] == "OEBPS/Text/chapter-1.xhtml"
        and unit["locator"]["part_count"] > 1
    ]

    assert len(parts) >= 3
    assert [unit["locator"]["part_index"] for unit in parts] == list(range(len(parts)))
    assert all(unit["locator"]["part_count"] == len(parts) for unit in parts)
    assert all(len(unit["source_text"]) <= 1_800 for unit in parts)
    assert "".join(unit["source_text"] + unit["joiner"] for unit in parts) == long_paragraph

    translations = {parts[0]["sequence"]: "FIRST-PART-TRANSLATED"}
    summary = build_translated_epub(source, output, manifest, translations, "fr")
    expected = (
        "FIRST-PART-TRANSLATED"
        + parts[0]["joiner"]
        + "".join(unit["source_text"] + unit["joiner"] for unit in parts[1:])
    )
    with zipfile.ZipFile(output) as archive:
        chapter = archive.read("OEBPS/Text/chapter-1.xhtml").decode()
    assert expected in chapter
    assert summary["translated_unit_count"] == 1
    assert summary["preserved_unit_count"] == len(manifest["text_units"]) - 1


@pytest.mark.parametrize(
    "variation",
    ["damaged", "malformed_xml", "encryption", "unsafe", "duplicate", "dtd"],
)
def test_damaged_protected_and_unsafe_epubs_are_rejected(tmp_path: Path, variation: str) -> None:
    source = tmp_path / f"{variation}.epub"
    if variation == "damaged":
        source.write_bytes(b"not a zip")
    elif variation == "malformed_xml":
        _write_epub(source, malformed_chapter=True)
    elif variation == "encryption":
        _write_epub(source, encryption_xml=True)
    elif variation == "unsafe":
        _write_epub(source, unsafe_member="../escape.txt")
    elif variation == "duplicate":
        _write_epub(source, duplicate_member=True)
    else:
        _write_epub(source, malicious_xml=True)
    _assert_rejected(source)


def test_encrypted_general_purpose_flag_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "flagged.epub"
    _write_epub(source)
    payload = bytearray(source.read_bytes())
    # Mark the first member encrypted in both its local and central headers.  Inspection rejects
    # the flag before it ever attempts decryption.
    local = payload.index(b"PK\x03\x04")
    central = payload.index(b"PK\x01\x02")
    struct.pack_into("<H", payload, local + 6, struct.unpack_from("<H", payload, local + 6)[0] | 1)
    struct.pack_into(
        "<H", payload, central + 8, struct.unpack_from("<H", payload, central + 8)[0] | 1
    )
    source.write_bytes(payload)

    error = _assert_rejected(source)
    assert "Encrypted" in error.message


def test_archive_resource_limits_reject_bombs_large_members_counts_and_depth(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fixture.epub"
    _write_epub(source)
    low_count = _settings(max_archive_files=3)
    assert "too many" in _assert_rejected(source, low_count).message

    low_total = _settings(max_archive_uncompressed_bytes=100)
    assert "total-size" in _assert_rejected(source, low_total).message

    low_member = _settings(
        max_archive_uncompressed_bytes=1_000_000,
        max_archive_member_bytes=32,
        max_archive_compression_ratio=1_000,
    )
    assert "member" in _assert_rejected(source, low_member).message

    deep = tmp_path / "deep.epub"
    _write_epub(deep, unsafe_member="a/b/c/d/e.txt")
    shallow = _settings(
        max_archive_uncompressed_bytes=1_000_000,
        max_archive_member_bytes=500_000,
        max_archive_compression_ratio=1_000,
        max_archive_path_depth=4,
    )
    assert "depth" in _assert_rejected(deep, shallow).message

    bomb = tmp_path / "bomb.epub"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("bomb.bin", b"0" * 100_000)
    strict_ratio = _settings(
        max_archive_uncompressed_bytes=1_000_000,
        max_archive_member_bytes=500_000,
        max_archive_compression_ratio=10,
    )
    assert "compression-ratio" in _assert_rejected(bomb, strict_ratio).message


def test_build_rejects_stale_manifest_and_source_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.epub"
    other = tmp_path / "other.epub"
    _write_epub(source)
    _write_epub(other)
    manifest = inspect_epub(source)
    with zipfile.ZipFile(other, "a") as archive:
        archive.comment = b"different"

    with pytest.raises(LinguaError):
        build_translated_epub(other, tmp_path / "out.epub", manifest, [], "fr")
    with pytest.raises(LinguaError):
        build_translated_epub(source, source, manifest, [], "fr")


def test_build_maps_independent_output_rejection_to_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.epub"
    output = tmp_path / "translated.epub"
    _write_epub(source)
    manifest = inspect_epub(source)

    def reject_output(_path: Path, _settings: object | None = None) -> dict[str, object]:
        raise LinguaError(ErrorCode.EPUB_INVALID, "synthetic output rejection")

    monkeypatch.setattr(epub_module, "validate_epub", reject_output)

    with pytest.raises(LinguaError) as caught:
        build_translated_epub(source, output, manifest, [], "fr")

    assert caught.value.code == ErrorCode.EPUB_VALIDATION_FAILED
    assert caught.value.details == {"cause_code": ErrorCode.EPUB_INVALID}
    assert not output.exists()
    assert list(tmp_path.glob(".translated.epub.*.tmp")) == []
