# Headless HTTP API

The optional FastAPI server exposes instance-scoped JSON/OpenAPI over the same pure core and local
runtime. It serves no product GUI, reader, application HTML/JavaScript/CSS, static assets, or SPA
fallback. FastAPI's operator-facing Swagger UI and ReDoc remain available at `/docs` and `/redoc`;
the machine contract is `/openapi.json`.

```bash
python -m pip install 'linguaspindle[server,cli]'
linguaspindle serve
```

The default bind is `127.0.0.1:8765`. `/` returns only a compact JSON descriptor containing name,
version, `headless` mode, health, docs, and OpenAPI paths.

There is no authentication or account model. Anyone with network reachability can operate the
instance. Keep it on loopback or behind an explicit private/access-controlled outer perimeter.

## Resource flow

Persistent asynchronous flow:

1. `POST /api/projects` creates an instance-local Project and immutable Source Artifact.
2. `POST /api/projects/{project_id}/jobs` queues a runtime Pipeline and returns `202` immediately.
3. Poll `GET /api/jobs/{job_id}` for durable Steps, logs, errors, controls, and Artifacts.
4. Download a completed Artifact through its `download_url`.

Caller-controlled novel flow:

1. `GET /api/projects/{project_id}/segments` returns stable core Segments from the immutable source,
   optionally overlaid with one persisted Job's state.
2. `POST /api/projects/{project_id}/segments/translate` translates exactly an explicit ID list and
   returns/persists a versioned translation batch.
3. The caller may edit/replace text in its own system.
4. `POST /api/projects/{project_id}/rebuild` rebuilds TXT/EPUB from only the supplied ID-to-text
   mapping, without calling a Provider, and returns a downloadable output Artifact.

The server uses ordinary request/response and Job polling. It defines no SSE or WebSocket contract.

## Main endpoints

| Method and path | Purpose |
| --- | --- |
| `GET /` | Headless service descriptor JSON. |
| `GET /health` | Process and SQLite readiness. |
| `GET /api/system` | Version, counts, recent Jobs, limits, and bind default. |
| `GET /api/adapters` | Manga Adapter manifests and current health. |
| `GET /api/providers` | Secret-free Provider status. |
| `GET /api/pipelines` | Versioned runtime TXT/EPUB/manga Presets. |
| `GET`, `POST /api/profiles` | List/create non-secret Translation Profiles. |
| `GET`, `POST /api/projects` | List/create Projects; create accepts one bounded multipart Source. |
| `GET`, `DELETE /api/projects/{id}` | Detail or confirmed deletion (`?confirmed=true`). |
| `POST /api/projects/{id}/jobs` | Queue an asynchronous persistent Job. |
| `GET /api/jobs` | List Jobs; optional `project_id` and `status`. |
| `GET /api/jobs/{id}` | Durable detail including Steps/logs/Artifacts. |
| `POST /api/jobs/{id}/pause` | Request pause at a safe boundary. |
| `POST /api/jobs/{id}/resume` | Requeue a paused Job. |
| `POST /api/jobs/{id}/cancel` | Request cancellation at a safe boundary. |
| `POST /api/jobs/{id}/retry` | Retry failed/partial work and downstream Steps. |
| `GET /api/projects/{id}/segments` | Stable TXT/EPUB source Segments; optional `job_id` overlay. |
| `POST /api/projects/{id}/segments/translate` | Explicit selected translation plus versioned JSON Artifact. |
| `POST /api/projects/{id}/rebuild` | Provider-free immutable-source rebuild from caller text. |
| `GET /api/projects/{id}/artifacts` | Project Artifacts; optional `job_id`. |
| `GET /api/artifacts/{id}` | Artifact metadata. |
| `GET /api/artifacts/{id}/download` | Verified payload file response. |
| `POST /api/projects/{id}/exports` | Latest completed export Artifacts. |

## Create a Project

Multipart fields:

```text
name
kind=novel|manga
source_language
target_language
source=<TXT|EPUB|CBZ|PNG|JPEG|WebP>
```

```bash
curl -sS -X POST http://127.0.0.1:8765/api/projects \
  -F 'name=Book' \
  -F 'kind=novel' \
  -F 'source_language=en' \
  -F 'target_language=zh-CN' \
  -F 'source=@book.epub;type=application/epub+zip'
```

EPUB target language must be a plausible BCP 47 tag such as `en`, `fr`, or `zh-CN`; rebuild writes
it into OPF/XHTML language metadata. Import always enforces the exact source-byte bound and rejects
empty or incompatible filename/kind combinations. EPUB and CBZ archives are inspected for archive
safety before Project publication. TXT decoding/content checks and single-image structural checks
run when the corresponding core operation prepares or inspects that immutable Source.

Queue a persistent Job:

```json
{
  "pipeline_key": "novel_epub_v1",
  "profile_id": null,
  "provider_id": "mock",
  "adapter_id": null
}
```

Omitting the Pipeline selects a compatible Preset from Project/source kind: TXT →
`novel_txt_v1`, EPUB → `novel_epub_v1`, manga → `manga_full_v1`. An incompatible explicit choice
returns `CONFIGURATION_ERROR`.

## Read stable Segments

```bash
curl -sS http://127.0.0.1:8765/api/projects/PROJECT_ID/segments
```

Each response includes `schema_version=segment.v1`, stable `segment_id`, `order`/`sequence`, source
format/Artifact/document/text/role, typed locator, source and translation-input hashes, and joiner.
With `?job_id=JOB_ID`, the server verifies that the Job belongs to the Project and overlays status,
translated text, model, reuse lineage, error, and QA findings. Without a matching persisted row,
status is `source`.

The Segments are freshly inspected from the immutable TXT/EPUB Source through the public core;
they are not SQLAlchemy row representations.

## Translate an explicit selection

```bash
curl -sS -X POST \
  http://127.0.0.1:8765/api/projects/PROJECT_ID/segments/translate \
  -H 'Content-Type: application/json' \
  -d '{
    "selected_segment_ids": ["SEGMENT_ID_1", "SEGMENT_ID_3"],
    "existing_translations": {"SEGMENT_ID_1": "Caller-owned text"},
    "provider_id": "mock",
    "style": "Preserve tone.",
    "prompt_version": "v1",
    "concurrency": 2,
    "max_retries": 2,
    "retry_backoff_seconds": 0.25
  }'
```

`selected_segment_ids` is required and means exactly the supplied IDs. `[]` is a deliberate no-op
and never translates all. Unknown IDs return `SEGMENT_NOT_FOUND` before a Provider call. Text in
`existing_translations` wins and is not sent to the Provider.

The response contains Project/source Artifact IDs, a `translation-batch.v1` result, and metadata/
download URL for the persisted `novel_translations` JSON Artifact. Records remain in source order
and retain source/manual/succeeded/failed/cancelled state, attempts, normalized usage, or per-
Segment error. Partial failure preserves successful records.

This endpoint is a synchronous core operation and is intended for an explicit caller-controlled
selection. Use the persistent Job endpoint for long background whole-project work.

## Rebuild from caller text

```bash
curl -sS -X POST http://127.0.0.1:8765/api/projects/PROJECT_ID/rebuild \
  -H 'Content-Type: application/json' \
  -d '{
    "translations": {
      "SEGMENT_ID_1": "Reviewed first paragraph.",
      "SEGMENT_ID_3": "Reviewed third paragraph."
    }
  }'
```

Rebuild invokes no Provider. It re-inspects the latest immutable novel Source, validates every ID,
and substitutes only the supplied text. Unmapped TXT spans/EPUB slots preserve source text. An
empty mapping therefore produces a source-text-preserving rebuilt output, not a Provider call.

TXT output is UTF-8/LF. EPUB output retains the structure/resource/validation policy in
[EPUB support](epub.md). The response contains `build-result.v1` and a downloadable immutable
`novel_export_txt` or `novel_export_epub` Artifact.

## Job states and controls

Runtime states are `queued`, `running`, `paused`, `cancelling`, `cancelled`, `succeeded`, `failed`,
and `partially_succeeded`.

- Queued pause/cancel can be immediate; active requests take effect at a Segment/page boundary.
- Resume requeues paused work and retains completed boundaries.
- Retry resets the earliest failed/partial Step and downstream work while preserving prior logs
  and attempt counts.
- Process interruption marks active work `PROCESS_INTERRUPTED`; retry is explicit.
- A current real manga Adapter call may finish/time out before page-boundary cancellation.
- Confirmed Project deletion is rejected while related Jobs are non-terminal.

## Upload/download and archive bounds

An outer ASGI guard caps every POST/PUT/PATCH request body at the source limit plus 1 MiB framing
allowance before FastAPI parses multipart or JSON content. Project publication additionally
enforces the exact source limit while streaming into the managed store. A failed pre-publication
EPUB/CBZ inspection removes staged bytes and publishes no usable Project. Request models also
bound selected-ID lists and translation maps; reverse proxies should retain a compatible global
request-body bound.

EPUB/CBZ member count, expanded/per-member bytes, compression ratio, and path depth use the
runtime's explicit `ArchiveLimits`; [EPUB support](epub.md) lists defaults. Reverse proxies need a
compatible but still bounded body limit.

Artifact download verifies the database identity, resolves a private safe path, checks stored
size, and returns an attachment `FileResponse` with `X-Content-Type-Options: nosniff`. Private
storage keys are never returned.

## Errors and secrets

Stable envelope:

```json
{
  "error": {
    "code": "SEGMENT_NOT_FOUND",
    "message": "Selected Segment ID is not present in the manifest",
    "details": {"unknown_segment_ids": ["..."]},
    "retryable": false
  }
}
```

Stable categories include configuration/dependency, upload/archive bounds, unsafe/invalid/
unsupported/protected EPUB, source mismatch, unknown Segment, Adapter unavailable, external
command, timeout, invalid format, model API, rate limit, cancellation, missing output, not found,
invalid state, process interruption, storage, and unknown failure. The shared OpenAPI response map
documents normalized envelopes for 400, 404, 409, 413, 422, 429, 500, 502, 503, and 504. Concrete
status mapping includes 413 for source/archive limits, 404 for missing resources, 409 for invalid
state, 429 for rate limiting, 502 for model transport, 503 for unavailable Adapters, and 504 for
timeouts.

Request models reject unknown fields. The API never accepts a key field; if a request body
contains the active runtime Provider key as text, it is rejected. Managed diagnostics and response
details are redacted. Configure Provider credentials only in the server process environment/
secret mechanism.

## Compatibility

The optional server retains the v0.2.0 Project/Job/Artifact lifecycle while adding stable public
Segment operations. Migration 0003 preserves existing rows and payloads; see the
[migration guide](migrations/v0.2-to-v0.3.md). Use the generated OpenAPI contract for clients and
treat undocumented fields as internal. The API contains no user/account/tenant/permission routes
or fields.
