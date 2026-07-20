from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from linguaspindle.config import Settings
from linguaspindle.interfaces.api import create_app

_RUN_BROWSER_TESTS = os.getenv("LINGUASPINDLE_RUN_BROWSER_TESTS") == "1"
_RUN_REAL_PROVIDER_TESTS = os.getenv("LINGUASPINDLE_RUN_REAL_PROVIDER_TESTS") == "1"
_BROWSER_BASE_URL = os.getenv("LINGUASPINDLE_BROWSER_BASE_URL", "").rstrip("/")
_BROWSER_EVIDENCE_DIR = os.getenv("LINGUASPINDLE_BROWSER_EVIDENCE_DIR", "")
_REAL_PROVIDER_EVIDENCE_DIR = os.getenv("LINGUASPINDLE_REAL_PROVIDER_EVIDENCE_DIR", "")
_REAL_PROVIDER_EXISTING_JOB_ID = os.getenv("LINGUASPINDLE_REAL_PROVIDER_EXISTING_JOB_ID", "")

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        not _RUN_BROWSER_TESTS,
        reason="set LINGUASPINDLE_RUN_BROWSER_TESTS=1 after installing Chromium",
    ),
]


def _start_server(tmp_path: Path) -> tuple[uvicorn.Server, threading.Thread, socket.socket, str]:
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
        name="browser-test-server",
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
        raise AssertionError("Live browser test server did not start")
    return server, thread, listener, f"http://127.0.0.1:{port}"


def _create_project(
    page,
    *,
    name: str,
    source: Path,
    kind: str = "novel",
    source_language: str = "en",
    target_language: str = "fr",
) -> str:
    page.goto(page.url.split("/#", maxsplit=1)[0] + "/#/projects/new")
    expect(page.get_by_role("heading", name="Create a project")).to_be_visible()
    page.get_by_label("Project name").fill(name)
    page.get_by_label("Project type").select_option(kind)
    page.get_by_label("Source language").fill(source_language)
    page.get_by_label("Target language").fill(target_language)
    page.get_by_label("Source file").set_input_files(source)
    page.get_by_role("button", name="Create project").click()
    page.wait_for_url(re.compile(r".*/#/projects/[0-9a-f-]+$"))
    expect(page.get_by_role("heading", name=name)).to_be_visible()
    return page.url.rsplit("/", maxsplit=1)[-1]


def _run_job(page, *, selector_label: str, selector_value: str) -> str:
    page.get_by_label(selector_label).select_option(selector_value)
    page.get_by_role("button", name="Create asynchronous Job").click()
    page.wait_for_url(re.compile(r".*/#/jobs/[0-9a-f-]+$"))
    return page.url.rsplit("/", maxsplit=1)[-1]


def _download(page, row, *, evidence_dir: Path | None, filename: str) -> tuple[bytes, str]:
    with page.expect_download() as download_info:
        row.get_by_role("link", name="Download").click()
    download = download_info.value
    if evidence_dir is not None:
        path = evidence_dir / filename
        download.save_as(path)
    else:
        temporary_path = download.path()
        assert temporary_path is not None
        path = Path(temporary_path)
    payload = path.read_bytes()
    return payload, hashlib.sha256(payload).hexdigest()


def _job_evidence(request, base_url: str, job_id: str) -> dict[str, object]:
    response = request.get(f"{base_url}/api/jobs/{job_id}")
    assert response.ok
    job = response.json()
    return {
        "id": job["id"],
        "project_id": job["project_id"],
        "status": job["status"],
        "error": job["error"],
        "steps": [
            {
                "id": step["id"],
                "key": step["key"],
                "status": step["status"],
                "attempt_count": step["attempt_count"],
                "input_artifact_ids": step["input_artifact_ids"],
                "output_artifact_ids": step["output_artifact_ids"],
                "logs": step["logs"],
            }
            for step in job["steps"]
        ],
        "artifacts": [
            {
                "id": artifact["id"],
                "kind": artifact["kind"],
                "checksum": artifact["checksum"],
                "size": artifact["size"],
            }
            for artifact in job["artifacts"]
        ],
    }


def _wait_for_job_terminal(request, base_url: str, job_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    last_job: dict = {}
    while time.monotonic() < deadline:
        response = request.get(f"{base_url}/api/jobs/{job_id}")
        assert response.ok
        last_job = response.json()
        if last_job["status"] in {
            "succeeded",
            "partially_succeeded",
            "failed",
            "cancelled",
        }:
            return last_job
        time.sleep(0.25)
    raise AssertionError(f"Job {job_id} did not reach a terminal state: {last_job.get('status')}")


def test_gui_mock_translation_download_and_failure_display(tmp_path) -> None:
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    listener: socket.socket | None = None
    if _BROWSER_BASE_URL:
        base_url = _BROWSER_BASE_URL
    else:
        server, thread, listener, base_url = _start_server(tmp_path)
    assert urlsplit(base_url).hostname in {"127.0.0.1", "::1", "localhost"}

    evidence_dir = Path(_BROWSER_EVIDENCE_DIR).resolve() if _BROWSER_EVIDENCE_DIR else None
    if evidence_dir is not None:
        evidence_dir.mkdir(parents=True, exist_ok=True)

    source = tmp_path / "browser.txt"
    source.write_text("Browser first.\n\nBrowser second.", encoding="utf-8")
    failing_source = tmp_path / "browser-failure.txt"
    failing_source.write_text("[[MOCK_FAIL]]", encoding="utf-8")
    manga_source = tmp_path / "browser-manga.png"
    manga_source.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )
    browser_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    unexpected_origins: set[str] = set()
    downloads: dict[str, dict[str, object]] = {}
    jobs: dict[str, dict[str, object]] = {}
    browser_version = "unknown"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            browser_version = browser.version
            context = browser.new_context(accept_downloads=True)
            trace_started = evidence_dir is not None
            if trace_started:
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.on("pageerror", lambda error: browser_errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text) if message.type == "error" else None
                ),
            )

            def record_failed_request(request) -> None:
                failure = str(request.failure)
                if "/api/artifacts/" in request.url and request.url.endswith("/download"):
                    if "ERR_ABORTED" in failure:
                        return
                failed_requests.append(f"{request.method} {request.url}: {failure}")

            page.on("requestfailed", record_failed_request)

            def record_origin(request) -> None:
                parsed = urlsplit(request.url)
                if (
                    parsed.scheme in {"http", "https"}
                    and request.url.split("/", 3)[:3] != base_url.split("/", 3)[:3]
                ):
                    unexpected_origins.add(f"{parsed.scheme}://{parsed.netloc}")

            page.on("request", record_origin)

            try:
                page.goto(base_url)
                expect(page).to_have_title("LinguaSpindle")
                expect(page.get_by_text("No login · loopback first")).to_be_visible()
                expect(
                    page.get_by_role("heading", name="Translation operations, at a glance")
                ).to_be_visible()
                expect(page.locator('input[type="password"]')).to_have_count(0)
                expect(
                    page.get_by_role(
                        "link", name=re.compile(r"^(log ?in|register|sign ?up)$", re.I)
                    )
                ).to_have_count(0)
                expect(
                    page.get_by_role(
                        "button", name=re.compile(r"^(log ?in|register|sign ?up)$", re.I)
                    )
                ).to_have_count(0)

                page.goto(f"{base_url}/#/settings")
                expect(page.get_by_role("heading", name="Adapters & Providers")).to_be_visible()
                expect(
                    page.get_by_role("heading", name="OpenAI-compatible Provider")
                ).to_be_visible()
                provider_response = context.request.get(f"{base_url}/api/providers")
                assert provider_response.ok
                openai_provider = next(
                    item for item in provider_response.json() if item["id"] == "openai-compatible"
                )
                provider_card = page.locator("article").filter(
                    has_text="OpenAI-compatible Provider"
                )
                if openai_provider["configured"]:
                    expect(provider_card.locator(".badge.available")).to_be_visible()
                else:
                    expect(page.get_by_text("Set LINGUASPINDLE_OPENAI_API_KEY")).to_be_visible()
                expect(
                    page.get_by_text("External service URL is not configured").first
                ).to_be_visible()
                if evidence_dir is not None:
                    page.screenshot(
                        path=evidence_dir / "01-runtime-capabilities.png", full_page=True
                    )

                novel_project_id = _create_project(page, name="Docker browser novel", source=source)
                novel_job_id = _run_job(
                    page, selector_label="Translation Provider", selector_value="mock"
                )
                expect(page.locator(".badge.succeeded").first).to_be_visible(timeout=20_000)
                expect(page.get_by_text("Step succeeded").first).to_be_visible()
                expect(page.get_by_role("heading", name="Steps")).to_be_visible()
                expect(page.get_by_role("heading", name="Job Artifacts")).to_be_visible()
                if evidence_dir is not None:
                    page.screenshot(
                        path=evidence_dir / "02-novel-job-succeeded.png", full_page=True
                    )
                jobs["novel"] = _job_evidence(context.request, base_url, novel_job_id)

                page.get_by_role("link", name="Project", exact=True).click()
                expect(page.get_by_role("heading", name="Novel results")).to_be_visible()
                expect(
                    page.locator(".segment").filter(has_text="[fr] Browser first.")
                ).to_be_visible()
                expect(page.get_by_text("Source · 1")).to_be_visible()
                expect(page.get_by_text("Translation · succeeded").first).to_be_visible()

                txt_row = page.locator(".list-row").filter(has_text="novel_export_txt")
                txt_payload, txt_sha256 = _download(
                    page,
                    txt_row,
                    evidence_dir=evidence_dir,
                    filename="novel-export.txt",
                )
                assert b"[fr] Browser first." in txt_payload
                downloads["novel_txt"] = {
                    "filename": "novel-export.txt",
                    "sha256": txt_sha256,
                    "size": len(txt_payload),
                }

                json_row = page.locator(".list-row").filter(has_text="novel_export_json")
                json_payload, json_sha256 = _download(
                    page,
                    json_row,
                    evidence_dir=evidence_dir,
                    filename="novel-export.json",
                )
                structured = json.loads(json_payload)
                assert structured["schema_version"] == 1
                assert structured["project"]["id"] == novel_project_id
                assert structured["job_id"] == novel_job_id
                assert structured["segments"][0]["translated_text"] == "[fr] Browser first."
                downloads["novel_json"] = {
                    "filename": "novel-export.json",
                    "sha256": json_sha256,
                    "size": len(json_payload),
                }

                _create_project(page, name="Docker browser failure", source=failing_source)
                failure_job_id = _run_job(
                    page, selector_label="Translation Provider", selector_value="mock"
                )
                expect(page.locator(".badge.partially_succeeded").first).to_be_visible(
                    timeout=20_000
                )
                expect(page.get_by_text("MODEL_API_ERROR", exact=True).first).to_be_visible()
                expect(page.get_by_text("Segment translation failed")).to_be_visible()
                jobs["expected_failure"] = _job_evidence(context.request, base_url, failure_job_id)
                if evidence_dir is not None:
                    page.screenshot(path=evidence_dir / "03-expected-failure.png", full_page=True)

                manga_project_id = _create_project(
                    page,
                    name="Docker browser manga",
                    source=manga_source,
                    kind="manga",
                    source_language="ja",
                    target_language="en",
                )
                manga_job_id = _run_job(
                    page, selector_label="Manga Adapter", selector_value="mock-manga"
                )
                expect(page.locator(".badge.succeeded").first).to_be_visible(timeout=20_000)
                expect(page.get_by_text("Step succeeded").first).to_be_visible()
                jobs["mock_manga"] = _job_evidence(context.request, base_url, manga_job_id)
                page.get_by_role("link", name="Project", exact=True).click()
                expect(page.get_by_text("manga_page_translated")).to_be_visible()
                expect(page.get_by_text("adapter_raw_output")).to_be_visible()
                cbz_row = page.locator(".list-row").filter(has_text="manga_export_cbz")
                cbz_payload, cbz_sha256 = _download(
                    page,
                    cbz_row,
                    evidence_dir=evidence_dir,
                    filename="mock-manga-export.cbz",
                )
                cbz_path = tmp_path / "downloaded.cbz"
                cbz_path.write_bytes(cbz_payload)
                with zipfile.ZipFile(cbz_path) as archive:
                    assert archive.namelist() == ["0001.png"]
                    assert archive.read("0001.png") == manga_source.read_bytes()
                downloads["mock_manga_cbz"] = {
                    "filename": "mock-manga-export.cbz",
                    "sha256": cbz_sha256,
                    "size": len(cbz_payload),
                }
                if evidence_dir is not None:
                    page.screenshot(path=evidence_dir / "04-mock-manga-project.png", full_page=True)

                unavailable_job_id = _run_job(
                    page,
                    selector_label="Manga Adapter",
                    selector_value="manga-image-translator-http",
                )
                expect(page.locator(".badge.failed").first).to_be_visible(timeout=20_000)
                expect(page.get_by_text("ADAPTER_UNAVAILABLE", exact=True).first).to_be_visible()
                expect(
                    page.get_by_text("External service URL is not configured").first
                ).to_be_visible()
                jobs["unconfigured_manga_adapter"] = _job_evidence(
                    context.request, base_url, unavailable_job_id
                )
                if evidence_dir is not None:
                    page.screenshot(
                        path=evidence_dir / "05-unconfigured-manga-adapter.png", full_page=True
                    )

                assert browser_errors == []
                assert console_errors == []
                assert failed_requests == []
                assert unexpected_origins == set()

                if evidence_dir is not None:
                    evidence = {
                        "base_url": base_url,
                        "browser": f"Chromium {browser_version}",
                        "projects": {
                            "novel": novel_project_id,
                            "manga": manga_project_id,
                        },
                        "jobs": jobs,
                        "downloads": downloads,
                        "browser_errors": browser_errors,
                        "console_errors": console_errors,
                        "failed_requests": failed_requests,
                        "unexpected_origins": sorted(unexpected_origins),
                    }
                    (evidence_dir / "browser-evidence.json").write_text(
                        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
            finally:
                if trace_started:
                    context.tracing.stop(path=evidence_dir / "browser-trace.zip")
                context.close()
                browser.close()
    finally:
        if server is not None and thread is not None and listener is not None:
            server.should_exit = True
            thread.join(10)
            listener.close()
            assert not thread.is_alive()


@pytest.mark.skipif(
    not _RUN_REAL_PROVIDER_TESTS,
    reason="set LINGUASPINDLE_RUN_REAL_PROVIDER_TESTS=1 for the opt-in paid Provider check",
)
def test_gui_real_provider_minimal_translation(tmp_path) -> None:
    assert _BROWSER_BASE_URL, "Real Provider acceptance must target the Docker GUI"
    base_url = _BROWSER_BASE_URL
    assert urlsplit(base_url).hostname in {"127.0.0.1", "::1", "localhost"}

    evidence_dir = (
        Path(_REAL_PROVIDER_EVIDENCE_DIR).resolve() if _REAL_PROVIDER_EVIDENCE_DIR else None
    )
    if evidence_dir is not None:
        evidence_dir.mkdir(parents=True, exist_ok=True)

    source = tmp_path / "real-provider-minimal.txt"
    source.write_text(
        "The rain stopped shortly before dawn.\n\n"
        "Mira opened the window and looked toward the quiet station.\n\n"
        "She decided to take the first train home.",
        encoding="utf-8",
    )
    browser_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    unexpected_origins: set[str] = set()
    browser_version = "unknown"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        browser_version = browser.version
        context = browser.new_context(accept_downloads=True)
        trace_started = evidence_dir is not None
        if trace_started:
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text) if message.type == "error" else None
            ),
        )

        def record_failed_request(request) -> None:
            failure = str(request.failure)
            if "/api/artifacts/" in request.url and request.url.endswith("/download"):
                if "ERR_ABORTED" in failure:
                    return
            failed_requests.append(f"{request.method} {request.url}: {failure}")

        page.on("requestfailed", record_failed_request)

        def record_origin(request) -> None:
            parsed = urlsplit(request.url)
            if (
                parsed.scheme in {"http", "https"}
                and request.url.split("/", 3)[:3] != base_url.split("/", 3)[:3]
            ):
                unexpected_origins.add(f"{parsed.scheme}://{parsed.netloc}")

        page.on("request", record_origin)

        try:
            page.goto(base_url)
            expect(page).to_have_title("LinguaSpindle")
            expect(page.get_by_text("No login · loopback first")).to_be_visible()
            expect(page.locator('input[type="password"]')).to_have_count(0)

            providers_response = context.request.get(f"{base_url}/api/providers")
            assert providers_response.ok
            provider = next(
                item for item in providers_response.json() if item["id"] == "openai-compatible"
            )
            assert provider["configured"] is True
            provider_url = urlsplit(provider["base_url"])
            provider_origin = f"{provider_url.scheme}://{provider_url.netloc}"

            page.goto(f"{base_url}/#/settings")
            provider_card = page.locator("article").filter(has_text="OpenAI-compatible Provider")
            expect(provider_card.locator(".badge.available")).to_be_visible()

            reused_existing_job = bool(_REAL_PROVIDER_EXISTING_JOB_ID)
            if reused_existing_job:
                job_id = _REAL_PROVIDER_EXISTING_JOB_ID
                existing_response = context.request.get(f"{base_url}/api/jobs/{job_id}")
                assert existing_response.ok
                existing_job = existing_response.json()
                assert existing_job["provider_id"] == "openai-compatible"
                project_id = existing_job["project_id"]
            else:
                project_id = _create_project(
                    page,
                    name="Real Provider acceptance v0.2.0",
                    source=source,
                    source_language="en",
                    target_language="zh-CN",
                )
                job_id = _run_job(
                    page,
                    selector_label="Translation Provider",
                    selector_value="openai-compatible",
                )

            terminal_job = _wait_for_job_terminal(context.request, base_url, job_id, 180)
            assert terminal_job["status"] == "succeeded"
            page.goto(f"{base_url}/#/jobs/{job_id}")
            expect(page.get_by_role("heading", name="succeeded", exact=True)).to_be_visible()
            expect(page.get_by_role("heading", name="Steps")).to_be_visible()
            expect(page.get_by_role("heading", name="Job Artifacts")).to_be_visible()
            expect(page.get_by_text("attempt 1").first).to_be_visible()
            expect(page.get_by_text("Step succeeded").first).to_be_visible()
            if evidence_dir is not None:
                page.screenshot(path=evidence_dir / "real-provider-succeeded.png", full_page=True)

            job = _job_evidence(context.request, base_url, job_id)
            assert job["status"] == "succeeded"
            assert job["error"] is None
            steps = job["steps"]
            assert isinstance(steps, list)
            assert all(step["status"] == "succeeded" for step in steps)
            assert all(step["attempt_count"] == 1 for step in steps)

            segments_response = context.request.get(
                f"{base_url}/api/projects/{project_id}/segments?job_id={job_id}"
            )
            assert segments_response.ok
            segments = segments_response.json()
            assert len(segments) == 3
            assert all(segment["status"] == "succeeded" for segment in segments)
            translations = [segment["translated_text"] for segment in segments]
            assert all(isinstance(text, str) and text.strip() for text in translations)
            assert all(
                translated.strip() != segment["source_text"].strip()
                for translated, segment in zip(translations, segments, strict=True)
            )
            assert all(re.search(r"[\u3400-\u9fff]", text) for text in translations)
            assert not any(text.startswith("[zh-CN]") for text in translations)
            assert "雨" in translations[0]
            assert re.search(r"黎明|天亮|拂晓|破晓|清晨", translations[0])
            assert "窗" in translations[1] and "站" in translations[1]
            assert re.search(r"火车|列车", translations[2])
            assert re.search(r"家|回", translations[2])

            page.get_by_role("link", name="Project", exact=True).click()
            expect(page.get_by_role("heading", name="Novel results")).to_be_visible()
            expect(page.get_by_text("Translation · succeeded")).to_have_count(3)

            txt_row = page.locator(".list-row").filter(has_text="novel_export_txt")
            txt_payload, txt_sha256 = _download(
                page,
                txt_row,
                evidence_dir=evidence_dir,
                filename="real-provider-export.txt",
            )
            json_row = page.locator(".list-row").filter(has_text="novel_export_json")
            json_payload, json_sha256 = _download(
                page,
                json_row,
                evidence_dir=evidence_dir,
                filename="real-provider-export.json",
            )
            structured = json.loads(json_payload)
            assert structured["project"]["id"] == project_id
            assert structured["job_id"] == job_id
            assert len(structured["segments"]) == 3
            assert [item["translated_text"] for item in structured["segments"]] == translations
            assert all(text.encode() in txt_payload for text in translations)

            usage_calls = [
                log["details"]["usage"]
                for step in steps
                for log in step["logs"]
                if log["message"] == "Provider usage reported"
            ]
            usage: dict[str, object] | str = "not provided"
            if usage_calls:
                usage = {
                    "calls": usage_calls,
                    "totals": {
                        name: sum(call.get(name, 0) for call in usage_calls)
                        for name in ("prompt_tokens", "completion_tokens", "total_tokens")
                        if any(name in call for call in usage_calls)
                    },
                }

            assert browser_errors == []
            assert console_errors == []
            assert failed_requests == []
            assert unexpected_origins == set()

            if evidence_dir is not None:
                evidence = {
                    "base_url": base_url,
                    "browser": f"Chromium {browser_version}",
                    "provider": {
                        "id": provider["id"],
                        "model": provider["model"],
                        "origin": provider_origin,
                        "configured": provider["configured"],
                    },
                    "project_id": project_id,
                    "reused_existing_job": reused_existing_job,
                    "job": job,
                    "segments": segments,
                    "usage": usage,
                    "downloads": {
                        "txt": {
                            "filename": "real-provider-export.txt",
                            "sha256": txt_sha256,
                            "size": len(txt_payload),
                        },
                        "json": {
                            "filename": "real-provider-export.json",
                            "sha256": json_sha256,
                            "size": len(json_payload),
                        },
                    },
                    "browser_errors": browser_errors,
                    "console_errors": console_errors,
                    "failed_requests": failed_requests,
                    "unexpected_origins": sorted(unexpected_origins),
                }
                (evidence_dir / "real-provider-evidence.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        finally:
            if trace_started:
                context.tracing.stop(path=evidence_dir / "real-provider-trace.zip")
            context.close()
            browser.close()
