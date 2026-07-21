from __future__ import annotations

import asyncio
import json
from io import BytesIO
from pathlib import Path

import httpx

from linguaspindle.config import Settings
from linguaspindle.core import inspect_document
from linguaspindle.interfaces.api import create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EPUB_SAMPLE = (
    REPOSITORY_ROOT
    / "acceptance"
    / "v0.2.0"
    / "artifacts"
    / "samples"
    / "epub"
    / "source-multichapter.epub"
)


async def _document_api_flow(data_dir) -> None:
    application = create_app(Settings.from_env(data_dir), start_worker=False)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            source_payload = b"First paragraph.\r\n\r\nSecond paragraph."
            created = await client.post(
                "/api/projects",
                data={
                    "name": "Headless document API",
                    "kind": "novel",
                    "source_language": "en",
                    "target_language": "fr",
                },
                files={"source": ("source.txt", source_payload, "text/plain")},
            )
            assert created.status_code == 201, created.text
            project = created.json()
            project_id = project["id"]
            source_artifact = next(
                artifact
                for artifact in project["artifacts"]
                if artifact["kind"] == "source_original"
            )

            inspected = await client.get(f"/api/projects/{project_id}/segments")
            repeated = await client.get(f"/api/projects/{project_id}/segments")
            assert inspected.status_code == 200, inspected.text
            assert repeated.json() == inspected.json()
            segments = inspected.json()
            assert [item["source_text"] for item in segments] == [
                "First paragraph.",
                "Second paragraph.",
            ]
            assert [item["sequence"] for item in segments] == [0, 1]
            assert all(item["schema_version"] == "segment.v1" for item in segments)
            assert all(item["source_format"] == "txt" for item in segments)
            assert all(item["source_artifact_id"] == source_artifact["id"] for item in segments)
            first_id, second_id = (item["segment_id"] for item in segments)

            selected = await client.post(
                f"/api/projects/{project_id}/segments/translate",
                json={"provider_id": "mock", "selected_segment_ids": [second_id]},
            )
            assert selected.status_code == 200, selected.text
            selected_payload = selected.json()
            result = selected_payload["result"]
            assert result["schema_version"] == "translation-batch.v1"
            assert result["status"] == "succeeded"
            assert result["selected_segment_ids"] == [second_id]
            assert [record["segment_id"] for record in result["records"]] == [
                first_id,
                second_id,
            ]
            assert result["records"][0]["status"] == "source"
            assert result["records"][0]["translated_text"] is None
            assert result["records"][1]["status"] == "succeeded"
            assert result["records"][1]["translated_text"] == "[fr] Second paragraph."
            assert selected_payload["artifact"]["kind"] == "novel_translations"
            batch_download = await client.get(selected_payload["artifact"]["download_url"])
            assert batch_download.status_code == 200
            assert json.loads(batch_download.content) == result

            empty = await client.post(
                f"/api/projects/{project_id}/segments/translate",
                json={"selected_segment_ids": []},
            )
            assert empty.status_code == 200, empty.text
            assert empty.json()["result"]["status"] == "noop"
            assert all(record["status"] == "source" for record in empty.json()["result"]["records"])

            caller_owned = await client.post(
                f"/api/projects/{project_id}/segments/translate",
                json={
                    "selected_segment_ids": [second_id],
                    "existing_translations": {second_id: "Texte fourni par l'appelant."},
                },
            )
            assert caller_owned.status_code == 200, caller_owned.text
            supplied_record = caller_owned.json()["result"]["records"][1]
            assert supplied_record["status"] == "manual"
            assert supplied_record["translated_text"] == "Texte fourni par l'appelant."
            assert supplied_record["attempts"] == 0

            unknown = await client.post(
                f"/api/projects/{project_id}/segments/translate",
                json={"selected_segment_ids": ["not-a-segment"]},
            )
            assert unknown.status_code == 400
            assert unknown.json()["error"]["code"] == "SEGMENT_NOT_FOUND"

            oversized_selection = await client.post(
                f"/api/projects/{project_id}/segments/translate",
                json={"selected_segment_ids": [second_id] * 513},
            )
            assert oversized_selection.status_code == 422

            rebuilt = await client.post(
                f"/api/projects/{project_id}/rebuild",
                json={"translations": {first_id: "Paragraphe corrige."}},
            )
            assert rebuilt.status_code == 200, rebuilt.text
            rebuilt_payload = rebuilt.json()
            assert rebuilt_payload["build"]["schema_version"] == "build-result.v1"
            assert rebuilt_payload["build"]["translated_count"] == 1
            assert rebuilt_payload["build"]["preserved_count"] == 1
            assert rebuilt_payload["artifact"]["kind"] == "novel_export_txt"
            assert rebuilt_payload["artifact"]["job_id"] is None
            output = await client.get(rebuilt_payload["artifact"]["download_url"])
            assert output.status_code == 200
            assert output.content.decode() == "Paragraphe corrige.\n\nSecond paragraph."

            source_download = await client.get(source_artifact["download_url"])
            assert source_download.content == source_payload

            unknown_rebuild = await client.post(
                f"/api/projects/{project_id}/rebuild",
                json={"translations": {"not-a-segment": "no"}},
            )
            assert unknown_rebuild.status_code == 400
            assert unknown_rebuild.json()["error"]["code"] == "SEGMENT_NOT_FOUND"

            openapi = (await client.get("/openapi.json")).json()
            paths = openapi["paths"]
            assert paths["/api/projects/{project_id}/segments"]["get"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]["items"] == {
                "$ref": "#/components/schemas/SegmentResponse"
            }
            assert paths["/api/projects/{project_id}/segments/translate"]["post"]["responses"][
                "200"
            ]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/SelectedTranslationResponse"
            }
            assert paths["/api/projects/{project_id}/rebuild"]["post"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/RebuildDocumentResponse"
            }
            assert {"429", "500", "502", "503", "504"}.issubset(
                paths["/api/projects/{project_id}/segments/translate"]["post"]["responses"]
            )


def test_headless_document_api_supports_segments_selection_and_manual_rebuild(tmp_path) -> None:
    asyncio.run(_document_api_flow(tmp_path / "headless-document-api"))


async def _request_body_limit_flow(data_dir) -> None:
    application = create_app(
        Settings(data_dir=data_dir, max_upload_bytes=1),
        start_worker=False,
    )
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/projects/not-created/rebuild",
                json={"translations": {"segment": "x" * (1024 * 1024 + 1)}},
            )
            assert response.status_code == 413
            assert response.json()["error"]["code"] == "UPLOAD_TOO_LARGE"


def test_headless_api_bounds_all_mutating_request_bodies(tmp_path) -> None:
    asyncio.run(_request_body_limit_flow(tmp_path / "headless-body-limit"))


async def _epub_document_api_flow(data_dir) -> None:
    source_payload = EPUB_SAMPLE.read_bytes()
    application = create_app(Settings.from_env(data_dir), start_worker=False)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/projects",
                data={
                    "name": "Headless EPUB API",
                    "kind": "novel",
                    "source_language": "en",
                    "target_language": "fr",
                },
                files={
                    "source": (
                        "source-multichapter.epub",
                        source_payload,
                        "application/epub+zip",
                    )
                },
            )
            assert created.status_code == 201, created.text
            project = created.json()
            source_artifact = next(
                artifact
                for artifact in project["artifacts"]
                if artifact["kind"] == "source_original"
            )

            inspected = await client.get(f"/api/projects/{project['id']}/segments")
            assert inspected.status_code == 200, inspected.text
            segments = inspected.json()
            assert len(segments) > 1
            assert {segment["source_format"] for segment in segments} == {"epub3"}
            selected = next(segment for segment in segments if segment["content_role"] == "xhtml")

            translated = await client.post(
                f"/api/projects/{project['id']}/segments/translate",
                json={"selected_segment_ids": [selected["segment_id"]]},
            )
            assert translated.status_code == 200, translated.text
            translated_records = translated.json()["result"]["records"]
            assert sum(record["status"] == "succeeded" for record in translated_records) == 1
            assert (
                next(
                    record
                    for record in translated_records
                    if record["segment_id"] == selected["segment_id"]
                )["translated_text"]
                == f"[fr] {selected['source_text']}"
            )

            manual_text = "EPUB manual API reconstruction"
            rebuilt = await client.post(
                f"/api/projects/{project['id']}/rebuild",
                json={"translations": {selected["segment_id"]: manual_text}},
            )
            assert rebuilt.status_code == 200, rebuilt.text
            assert rebuilt.json()["build"]["source_format"] == "epub3"
            assert rebuilt.json()["artifact"]["kind"] == "novel_export_epub"
            output = await client.get(rebuilt.json()["artifact"]["download_url"])
            assert output.status_code == 200
            rebuilt_manifest = inspect_document(BytesIO(output.content), filename="rebuilt.epub")
            assert any(segment.source_text == manual_text for segment in rebuilt_manifest.segments)

            source_download = await client.get(source_artifact["download_url"])
            assert source_download.content == source_payload


def test_headless_document_api_supports_epub_selection_and_rebuild(tmp_path) -> None:
    asyncio.run(_epub_document_api_flow(tmp_path / "headless-epub-api"))


async def _project_type_and_secret_flow(data_dir) -> None:
    runtime_secret = "sk-" + "runtime-only-headless-api"
    application = create_app(
        Settings(data_dir=data_dir, openai_api_key=runtime_secret),
        start_worker=False,
    )
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            manga = await client.post(
                "/api/projects",
                data={
                    "name": "Manga remains asynchronous",
                    "kind": "manga",
                    "source_language": "ja",
                    "target_language": "en",
                },
                files={"source": ("page.png", b"not-yet-decoded", "image/png")},
            )
            assert manga.status_code == 201, manga.text
            rejected = await client.get(f"/api/projects/{manga.json()['id']}/segments")
            assert rejected.status_code == 400
            assert rejected.json()["error"]["code"] == "INVALID_FORMAT"

            novel = await client.post(
                "/api/projects",
                data={
                    "name": "Secret boundary",
                    "kind": "novel",
                    "source_language": "en",
                    "target_language": "fr",
                },
                files={"source": ("source.txt", b"safe source", "text/plain")},
            )
            segment_id = (await client.get(f"/api/projects/{novel.json()['id']}/segments")).json()[
                0
            ]["segment_id"]
            secret_request = await client.post(
                f"/api/projects/{novel.json()['id']}/segments/translate",
                json={
                    "selected_segment_ids": [segment_id],
                    "existing_translations": {segment_id: runtime_secret},
                },
            )
            assert secret_request.status_code == 400
            assert secret_request.json()["error"]["code"] == "CONFIGURATION_ERROR"
            assert runtime_secret not in secret_request.text


def test_document_api_rejects_manga_and_runtime_secret_input(tmp_path) -> None:
    asyncio.run(_project_type_and_secret_flow(tmp_path / "headless-document-boundaries"))
