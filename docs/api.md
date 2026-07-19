# HTTP API

LinguaSpindle exposes a single-instance, no-authentication API over the shared application and
orchestration core. It is intended for loopback or an operator-controlled private perimeter.

Interactive OpenAPI is served at `/docs`; the machine contract is `/openapi.json`.

## Resource flow

1. Create a Project and immutable Source with multipart `POST /api/projects`.
2. Optionally create a non-secret Translation Profile with `POST /api/profiles`.
3. Queue a Job with `POST /api/projects/{project_id}/jobs`; the response is immediate (`202`).
4. Poll `GET /api/jobs/{job_id}` for persisted Job, Step, log, error, and Artifact state.
5. Inspect segments or download final Artifacts.

The GUI uses polling as the only v0.1.0 progress transport. There is no SSE or WebSocket contract.

## Main endpoints

| Method and path | Purpose |
| --- | --- |
| `GET /health` | Process and SQLite readiness. |
| `GET /api/system` | Version, counts, recent Jobs, and bind default. |
| `GET /api/adapters` | Manifest plus live Adapter health. |
| `GET /api/providers` | Secret-free Provider configuration status. |
| `GET /api/pipelines` | Versioned ordered Pipeline Presets. |
| `GET`, `POST /api/profiles` | List/create non-secret Translation Profiles. |
| `GET`, `POST /api/projects` | List/create Projects. Create is multipart. |
| `GET`, `DELETE /api/projects/{id}` | Detail or confirmed deletion (`?confirmed=true`). |
| `POST /api/projects/{id}/jobs` | Queue an asynchronous Job. |
| `GET /api/jobs` | List Jobs, optionally filtering `project_id` and `status`. |
| `GET /api/jobs/{id}` | Durable detail including Steps/logs/Artifacts. |
| `POST /api/jobs/{id}/pause` | Request pause at a safe boundary. |
| `POST /api/jobs/{id}/resume` | Requeue a paused Job. |
| `POST /api/jobs/{id}/cancel` | Request cancellation at a safe boundary. |
| `POST /api/jobs/{id}/retry` | Retry failed/partial work and downstream Steps. |
| `GET /api/projects/{id}/segments` | Latest Job's novel results; optional `job_id`. |
| `GET /api/projects/{id}/artifacts` | Project Artifacts; optional `job_id`. |
| `GET /api/artifacts/{id}` | Artifact metadata. |
| `GET /api/artifacts/{id}/download` | Payload with attachment disposition. |
| `POST /api/projects/{id}/exports` | Return latest completed export Artifacts. |

## Create requests

Project multipart fields:

```text
name, kind=novel|manga, source_language, target_language, source=<file>
```

Job JSON:

```json
{
  "pipeline_key": "novel_txt_v1",
  "profile_id": null,
  "provider_id": "mock",
  "adapter_id": null
}
```

Omitted Pipeline selects the default for Project kind. Manga Jobs default to `mock-manga`; use
`manga-image-translator-http` only after its health is ready.

The Profile endpoint accepts source/target language, style, prompt template/version, batch size,
model parameters, Provider ID, and model. It does not accept an API key. Unknown fields are
rejected, validation responses omit submitted values, and `model`/`messages` cannot override the
Provider request envelope through model parameters.

## Job states and controls

`queued`, `running`, `paused`, `cancelling`, `cancelled`, `succeeded`, `failed`, and
`partially_succeeded` are persisted.

- Pause on a queued Job is immediate. Pause during translation is acknowledged through
  `control_request=\"pause\"`; the Job becomes `paused` at the next segment/page boundary.
- Resume changes a paused Step to pending and requeues the Job. Already successful segments and
  Steps are reused.
- Cancel on queued/paused work is immediate. Running work first becomes `cancelling`; pending
  Steps become cancelled only after active work reaches a safe boundary.
- Retry is valid for failed/partial Jobs. The earliest failed/partial Step and its downstream
  Steps are reset; upstream successes and prior logs/attempt counts remain.
- Process interruption marks the active Step and Job `failed` with `PROCESS_INTERRUPTED`.

## Errors

Application errors have a stable envelope:

```json
{
  "error": {
    "code": "ADAPTER_UNAVAILABLE",
    "message": "External service URL is not configured",
    "details": {},
    "retryable": true
  }
}
```

Stable categories include configuration, Adapter unavailable, external command, timeout, invalid
format, model API, rate limit, cancellation, missing output, not found, invalid state, interrupted
process, storage, and unknown errors. Managed diagnostics are redacted before persistence and
serialization. Never rely on raw third-party body text as a machine contract.

## Compatibility

v0.1.0 has no formal external client package. Use OpenAPI and treat undocumented response fields
as internal. Artifact IDs are the cross-boundary payload identity; private filesystem storage keys
are never returned. The API intentionally contains no user/account/tenant/permission routes or
fields.
