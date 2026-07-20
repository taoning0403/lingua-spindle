from __future__ import annotations

import asyncio
import io
import os
import re
import socket
import threading
import time
import zipfile
from pathlib import Path

import httpx
import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from linguaspindle.config import Settings
from linguaspindle.interfaces.api import create_app


def _epub_fixture(path: Path, *, first_paragraph: str = "Browser EPUB first.") -> None:
    container = b"""<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
    package = b"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="book-id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">urn:uuid:gui-epub-fixture</dc:identifier>
    <dc:title>Safe &lt;img src=x onerror=alert(1)&gt;</dc:title>
    <dc:creator>Browser Author</dc:creator>
    <dc:language>en</dc:language>
    <meta property="dcterms:modified">2026-07-20T00:00:00Z</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="chapter"/></spine>
</package>"""
    navigation = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title>Contents</title></head>
  <body><nav epub:type="toc"><ol><li>
    <a href="chapter.xhtml">Browser chapter</a>
  </li></ol></nav></body>
</html>"""
    chapter = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Browser chapter</title></head>
  <body>
    <h1>Browser chapter</h1>
    <p>{first_paragraph}</p>
    <p>Browser EPUB second.</p>
  </body>
</html>""".encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/package.opf", package)
        archive.writestr("OPS/nav.xhtml", navigation)
        archive.writestr("OPS/chapter.xhtml", chapter)


async def _read_web_assets(data_dir: Path) -> tuple[str, str, str]:
    application = create_app(Settings(data_dir=data_dir), start_worker=False)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            responses = await asyncio.gather(
                client.get("/"), client.get("/app.js"), client.get("/styles.css")
            )
            assert all(response.status_code == 200 for response in responses)
            return tuple(response.text for response in responses)  # type: ignore[return-value]


def test_epub_gui_assets_advertise_format_and_escape_imported_text(tmp_path: Path) -> None:
    index, javascript, stylesheet = asyncio.run(_read_web_assets(tmp_path / "asset-data"))

    assert "TXT · EPUB · manga" in index
    assert 'accept=".txt,.epub"' in javascript
    assert "Novel (TXT / EPUB 2/3)" in javascript
    assert "EPUB package manifest" in javascript
    assert "Translated EPUB" in javascript
    assert "novel_export_epub" in javascript
    assert "segment.source_document" in javascript
    assert "segment.content_role" in javascript
    assert "log.details.document" in javascript
    assert "current-document" in javascript
    assert "escapeHtml(segment.source_text)" in javascript
    assert "escapeHtml(segment.translated_text" in javascript
    assert "selection.textContent" in javascript
    assert "hint.textContent" in javascript
    assert "DOMParser" not in javascript
    assert "insertAdjacentHTML" not in javascript
    assert "srcdoc" not in javascript
    assert ".metadata-grid" in stylesheet
    assert ".segment-context" in stylesheet


def _start_server(
    tmp_path: Path,
) -> tuple[uvicorn.Server, threading.Thread, socket.socket, str]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    settings = Settings(data_dir=tmp_path / "browser-data", worker_poll_seconds=0.02)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings),
            host="127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
        )
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        name="epub-gui-test-server",
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not server.started and thread.is_alive():
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(2)
        listener.close()
        raise AssertionError("Live EPUB GUI test server did not start")
    return server, thread, listener, f"http://127.0.0.1:{port}"


@pytest.mark.browser
@pytest.mark.skipif(
    os.getenv("LINGUASPINDLE_RUN_BROWSER_TESTS") != "1",
    reason="set LINGUASPINDLE_RUN_BROWSER_TESTS=1 after installing Chromium",
)
def test_epub_gui_import_run_results_and_download(tmp_path: Path) -> None:
    source = tmp_path / "browser.epub"
    _epub_fixture(source)
    failing_source = tmp_path / "browser-failure.epub"
    _epub_fixture(failing_source, first_paragraph="[[MOCK_FAIL]] Expected browser failure.")
    server, thread, listener, base_url = _start_server(tmp_path)
    console_errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text) if message.type == "error" else None
                ),
            )

            page.goto(f"{base_url}/#/projects/new")
            expect(page.get_by_role("heading", name="Create a project")).to_be_visible()
            expect(
                page.get_by_role("link", name=re.compile(r"^(log ?in|register|sign ?up)$", re.I))
            ).to_have_count(0)
            expect(
                page.get_by_role("button", name=re.compile(r"^(log ?in|register|sign ?up)$", re.I))
            ).to_have_count(0)
            expect(page.get_by_label("Project type")).to_contain_text("Novel (TXT / EPUB 2/3)")
            assert ".epub" in (page.get_by_label("Source file").get_attribute("accept") or "")
            page.get_by_label("Project name").fill("Browser EPUB project")
            page.get_by_label("Source language").fill("en")
            page.get_by_label("Target language").fill("fr")
            page.get_by_label("Source file").set_input_files(source)
            expect(page.get_by_text("EPUB package", exact=False)).to_be_visible()
            page.get_by_role("button", name="Create project").click()
            page.wait_for_url(re.compile(r".*/#/projects/[0-9a-f-]+$"))

            expect(page.get_by_role("heading", name="Browser EPUB project")).to_be_visible()
            expect(page.locator('[data-source-kind="epub"] .badge.format')).to_have_text("EPUB 3.0")
            expect(page.get_by_text("Browser Author", exact=True)).to_be_visible()
            expect(
                page.get_by_text("Safe <img src=x onerror=alert(1)>", exact=True)
            ).to_be_visible()
            expect(page.get_by_text("Spine chapters", exact=True)).to_be_visible()
            assert page.locator("img").count() == 0

            page.get_by_label("Translation Provider").select_option("mock")
            page.get_by_role("button", name="Create asynchronous Job").click()
            page.wait_for_url(re.compile(r".*/#/jobs/[0-9a-f-]+$"))
            expect(page.locator(".badge.succeeded").first).to_be_visible(timeout=20_000)
            expect(page.get_by_text("100% complete", exact=True)).to_be_visible()
            expect(page.get_by_role("heading", name="inspect epub")).to_be_visible()
            expect(page.get_by_role("heading", name="segment epub")).to_be_visible()
            expect(page.get_by_role("heading", name="quality check")).to_be_visible()
            expect(page.get_by_role("heading", name="export epub")).to_be_visible()
            expect(page.get_by_text("QA report", exact=True)).to_be_visible()
            expect(page.get_by_text("Translated EPUB", exact=True)).to_be_visible()
            expect(page.get_by_text("EPUB validation report", exact=True)).to_be_visible()
            expect(page.locator(".current-document").first).to_contain_text("OPS/")

            page.get_by_role("link", name="Project", exact=True).click()
            expect(page.get_by_role("heading", name="Novel results")).to_be_visible()
            expect(
                page.locator(".segment").filter(has_text="[fr] Browser EPUB first.")
            ).to_be_visible()
            expect(page.locator(".segment-context").first).to_be_visible()
            expect(page.get_by_text(re.compile(r"OPS/(nav|chapter)\.xhtml")).first).to_be_visible()

            epub_row = page.locator(".artifact-row").filter(has_text="novel_export_epub")
            expect(epub_row).to_be_visible()
            with page.expect_download() as download_info:
                epub_row.get_by_role("link", name="Download").click()
            downloaded = download_info.value.path()
            assert downloaded is not None
            payload = Path(downloaded).read_bytes()
            assert payload.startswith(b"PK")
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                assert archive.read("mimetype") == b"application/epub+zip"
                exported_chapter = archive.read("OPS/chapter.xhtml").decode("utf-8")
                assert "[fr] Browser EPUB first." in exported_chapter

            page.goto(f"{base_url}/#/projects/new")
            page.get_by_label("Project name").fill("Browser EPUB expected failure")
            page.get_by_label("Source language").fill("en")
            page.get_by_label("Target language").fill("fr")
            page.get_by_label("Source file").set_input_files(failing_source)
            page.get_by_role("button", name="Create project").click()
            page.wait_for_url(re.compile(r".*/#/projects/[0-9a-f-]+$"))
            page.get_by_label("Translation Provider").select_option("mock")
            page.get_by_role("button", name="Create asynchronous Job").click()
            page.wait_for_url(re.compile(r".*/#/jobs/[0-9a-f-]+$"))
            expect(page.locator(".badge.partially_succeeded").first).to_be_visible(timeout=20_000)
            expect(page.get_by_text("MODEL_API_ERROR", exact=True).first).to_be_visible()
            expect(page.get_by_text("Segment translation failed")).to_be_visible()
            page.get_by_role("link", name="Project", exact=True).click()
            expect(page.get_by_text("Segment has no successful translation.")).to_be_visible()

            assert console_errors == []
            context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()
