# LinguaSpindle v0.1.0 product contract

This document condenses the founding requirements into a durable repository source of truth. It
defines the target, not the current implementation. `docs/PROJECT_STATE.md` records what actually
exists, and ADRs record durable design decisions.

## Identity and position

- Product: **LinguaSpindle**
- Repository: `lingua-spindle`
- CLI command: `linguaspindle`
- Position: an open-source translation orchestration engine for novels and manga. It composes
  existing open-source OCR, inpainting, translation, and typesetting tools plus model services
  through unified Adapters, Pipelines, persistent Jobs, a Web GUI, a CLI, and an HTTP API.

LinguaSpindle is not expected to implement every translation algorithm itself.

## Permanent product boundaries

These constraints are not merely deferred v0.1.0 features:

1. **No user system, ever.** LinguaSpindle is a single-instance tool, not SaaS or a multi-user
   platform. It has no registration, login, account, administrator, role, permission, team,
   organization, tenant, ownership, quota, project membership, or collaboration model. The GUI
   opens directly to the tool. All projects, jobs, configurations, glossaries, adapters, and
   artifacts belong directly to the running instance.
2. **Standalone operation.** LinguaSpindle does not depend on `novel-platform`. A future
   integration may call LinguaSpindle over HTTP, but cannot share databases, internal domain
   objects, identities, or data mutation.
3. **One program across environments.** Windows local, Linux local, Ubuntu server, Docker, and
   non-Docker execution use the same business implementation. GUI, CLI, and API reuse the same
   application and orchestration layers.
4. **Loopback by default.** The server listens only on a local address unless the operator opts
   in. Documentation must warn against direct public exposure and describe an outer reverse
   proxy, private network, Tailscale, Cloudflare Access, or similar perimeter for remote access.
   That perimeter is not an application account model.

ADR 0001 formalizes the first and fourth boundaries.

## v0.1.0 outcome

v0.1.0 establishes a real, extensible, restart-safe orchestration foundation. It must:

- start the Web GUI and HTTP API;
- create translation projects through GUI, CLI, or API;
- import at least one novel or manga source;
- select a Pipeline and translation configuration;
- create persistent background Jobs with inspectable Steps, logs, and Artifacts;
- recover durable state after process or container restart;
- call at least one real OpenAI-compatible translation endpoint;
- call at least one real maintained external open-source manga tool through an Adapter;
- export structured translation results and final artifacts; and
- demonstrate and test the full core flow without a paid key or heavyweight model.

Complete end-to-end behavior matters more than broad format coverage or a professional editing
suite.

## Architectural responsibilities

- **Interface layer:** Web GUI, CLI, and HTTP API adapt input/output only. They do not implement
  Pipelines or invoke third-party tools directly.
- **Application layer:** creates projects, imports sources, creates and controls Jobs, queries
  state, manages configuration, and exports results for all interfaces.
- **Orchestration core:** executes ordered Pipeline Steps, persists lifecycle and progress,
  supports retry/pause/resume/cancel, passes intermediate Artifacts, normalizes errors, records
  logs, and recovers after restart. v0.1.0 is a simple sequential engine, not a general DAG or
  distributed workflow platform.
- **Adapter runtime:** normalizes external subprocess/CLI, independent-container, and HTTP-service
  integrations. Pipelines must not depend on a tool's arguments, directory layout, or raw logs.
- **Artifact store:** stores immutable inputs, intermediate outputs, final outputs, logs, QA, and
  raw Adapter results. The database stores status and metadata; large payloads use file storage.

## Core concepts

- **Project:** long-lived Novel or Manga translation work.
- **Source:** immutable imported file or collection; never overwrite in place.
- **Job:** one Pipeline execution for a Project. A Project can have many Jobs.
- **Step Run:** persisted execution record with status, times, input/output Artifacts, Adapter,
  error, retry count, logs, and a non-secret configuration snapshot.
- **Artifact:** uniform identity for every input, intermediate result, report, and final result.
- **Pipeline Preset:** ready-to-run workflow definition; no drag-and-drop editor in v0.1.0.
- **Adapter:** uniform declaration and invocation boundary for an external tool or service.
- **Translation Provider:** uniform model or translation-service interface.
- **Translation Profile:** non-secret language, style, context, prompt, batch, and model-parameter
  policy kept separate from API keys.

## Functional scope

### Projects and sources

Create, list, inspect, delete, and export Novel and Manga projects; set name and language pair;
import sources; inspect Job history and Artifacts. Destructive deletion must state its impact but
does not require a permission system.

### Novel minimum flow

TXT is mandatory:

```text
import TXT -> detect encoding -> extract -> paragraph-aware segmentation
-> Translation Provider -> persist source/translation pairs -> basic QA
-> translated TXT + structured JSON
```

Persist segment order, source, translation, status, model, Translation Profile, Prompt version,
and error. Failed segments are retryable. The GUI must show source, translation, state, and QA.
EPUB is optional only if it does not jeopardize v0.1.0.

### Manga minimum flow

Accept an image directory or CBZ. Use the selected real external Adapter either as a complete
manga pipeline or as OCR/inpainting/typesetting around LinguaSpindle translation. Persist original
images, raw Adapter output, final images, logs, configuration snapshot, and failures; preserve OCR,
mask, or region data as Artifacts when the external tool exposes it.

### Translation providers

Implement an OpenAI-compatible Provider and a Mock Provider. OpenAI-compatible configuration
covers base URL, API key, model, timeout, concurrency limit, and retry policy. Keys must never
appear in displayed database state, logs, Job snapshots, exports, or artifacts. Mock supports
offline demos, automation, and recovery tests.

### Job control, recovery, and errors

Persist `queued`, `running`, `paused`, `cancelling`, `cancelled`, `succeeded`, `failed`, and
`partially_succeeded`. Support pause, resume, cancel, failed-step retry, progress, Step logs, and
failure inspection. If an Adapter cannot stop immediately, keep `cancelling` until a safe boundary;
never report a false cancellation.

After restart, Projects, Jobs, Artifacts, and completed Steps remain. An interrupted running Step
becomes explicitly recoverable or failed; completed Steps do not run again unconditionally.
Normalize at least configuration, Adapter unavailable, external command failure, timeout, invalid
format, model API, rate-limit, cancellation, missing output, and unknown errors into stable codes
with readable messages while retaining redacted raw diagnostics.

## Interface contract

### Web GUI

Provide these minimum task surfaces:

- dashboard with Project count, active/recent Jobs, Adapter health, and Provider configuration;
- Project list with name, type, language pair, latest Job/state, and creation time;
- Project creation with Novel/Manga source, language pair, Pipeline, and Translation Profile;
- Project detail with Sources, Job history, Artifacts, translation results, and exports;
- Job detail with overall/current-Step state, progress, every Step, logs, errors, input/output
  Artifacts, and pause/resume/cancel/retry controls;
- ordered novel source/translation/state/QA results; and
- Adapter capabilities/version/health/dependencies plus Provider configuration status.

Do not create account, profile, or login pages. Prefer one progress mechanism—polling or SSE—
rather than polling, SSE, and WebSocket simultaneously.

### CLI minimum commands

```text
linguaspindle serve
linguaspindle doctor
linguaspindle projects list|create|show
linguaspindle run
linguaspindle jobs list|show|pause|resume|cancel|retry
linguaspindle artifacts list
linguaspindle export
linguaspindle adapters list|doctor
```

`doctor` checks the data directory, database, file writes, external commands, Docker, Adapters,
Provider configuration, required fonts/models, ports, and application version. CLI operations go
through the same application layer and Job system as Web/API.

### HTTP API minimum surface

```text
GET    /health
GET    /api/system
GET    /api/adapters
GET    /api/providers
POST   /api/projects
GET    /api/projects
GET    /api/projects/{id}
DELETE /api/projects/{id}
POST   /api/projects/{id}/jobs
GET    /api/jobs
GET    /api/jobs/{id}
POST   /api/jobs/{id}/pause
POST   /api/jobs/{id}/resume
POST   /api/jobs/{id}/cancel
POST   /api/jobs/{id}/retry
GET    /api/projects/{id}/artifacts
GET    /api/artifacts/{id}
POST   /api/projects/{id}/exports
```

Creating a Job returns its ID immediately. Maintain OpenAPI. No API contract may introduce user,
account, tenant, role, or permission semantics.

## Storage, deployment, and security

Favor an out-of-box default of SQLite metadata plus a local Artifact directory unless documented
evaluation justifies another equally simple choice. Do not require PostgreSQL, Redis, Kafka,
Kubernetes, S3, or an external queue in v0.1.0. Concentrate mutable data under one configurable
root suitable for backup, migration, cleanup, and Docker volumes, with logical areas for database,
projects, artifacts, exports, logs, and cache.

Provide Dockerfile, Compose, persistent volume, health check, example environment, non-root
runtime, and a clear local port. Keep heavyweight tools, models, and GPU dependencies out of the
core image; run them as optional external processes/services. Default network binding is loopback.

## Adapter selection and licensing

Before selecting the first real manga Adapter, research currently maintained candidates and
verify CLI/API stability, Docker support, intermediate results, batch/cancel/progress behavior,
CPU/GPU needs, code license, model-weight license, font license, and automation suitability.
Record alternatives and rationale. Never copy an upstream project into this repository; integrate
by user-installed command, separate process/container, or HTTP service and provide mocks or
contract tests that avoid large downloads.

Each Adapter declares ID, display name, Adapter/upstream versions, invocation type, capabilities,
input/output formats, languages, GPU need, cancellation/progress support, health check,
configuration help, upstream URL/license, and whether LinguaSpindle modifications exist. Business
logic selects capabilities such as `novel_parse`, `text_segment`, `text_translate`,
`manga_detect`, `manga_ocr`, `manga_inpaint`, `manga_render`, `manga_full_pipeline`, `epub_build`,
or `cbz_build`, not a vendor name.

Core code is intended for Apache-2.0, subject to dependency review. Maintain `LICENSE`, bilingual
README, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `THIRD_PARTY_NOTICES.md`,
`CHANGELOG.md`, `.env.example`, architecture/Adapter/install/deployment documentation, and a
structured inventory of third-party code, versions/commits, licenses, integration method,
modifications, model weights, fonts, and redistribution status.
If an Adapter requires a separately installed upstream tool, say so explicitly; installation must
not silently download or execute unknown Internet code.

## Technology selection principles

Evaluate before selecting frameworks. Favor the Python OCR/AI/CLI ecosystem where appropriate,
consistent Windows/Linux behavior, a clear Web/backend separation, simple local and Docker start,
mature automation, and the least infrastructure that satisfies persistence and recovery. Python
for backend/CLI and TypeScript for Web are preferences, not mandates. Record the chosen Web
framework, database access, CLI, frontend, task execution, configuration, logging, and test stack
with reasons; do not split services merely to pursue a microservice label.

## Testing and release acceptance

- Unit tests cover Job/Step state, pause/resume/cancel/retry, Artifact links, Adapter errors,
  Provider retry, and configuration validation.
- Integration tests cover project/import/Job/Mock translation/export, restart persistence,
  failed retry, and CLI/API sharing one data store.
- Adapter contracts cover declarations, input/output, timeout, cancellation, errors, logs, and
  Artifact generation.
- Browser tests cover dashboard, novel project creation, Mock run, progress, translation,
  download, and failure display.
- Automation must not require paid keys or heavyweight model downloads.

v0.1.0 is accepted only when a clean environment and Compose start successfully; GUI has no
login; no user/tenant/permission model exists; TXT Mock translation works end to end through GUI,
CLI, and async API over the same services; pause/resume/cancel/retry and restart recovery work;
completed Steps are not repeated; TXT/JSON exports work; one real external manga Adapter is
integrated without vendored source; missing Adapter configuration is clear; keys are absent from
logs; tests/static checks/build pass; open-source licensing and third-party notices are complete;
loopback is the default; public-deployment warnings are explicit; and basic Windows plus
Linux/Docker execution is verified.

The final repository must include `acceptance/v0.1.0/` with actual commands and results, final
stack and structure, architecture decisions, tool research and Adapter rationale, local/Docker/
CLI/API usage, GUI summary, Windows and Linux/Docker evidence, known limits, and next-version
recommendations. Stop after all feasible v0.1.0 work; do not begin v0.2.0 automatically.

## Explicit exclusions

Do not implement or pre-model users, multi-tenancy, collaboration, permissions, resource-site
scraping, DRM handling, novel/manga downloaders, a reader, mobile clients, plugin marketplace,
drag-and-drop workflow editing, Photoshop-class editing, OCR training, distributed scheduling,
arbitrary internet plugin installation, exhaustive formats/tools/providers, or formal
`novel-platform` integration in v0.1.0.

## Required work order

1. Check name availability on GitHub, PyPI, npm, and common container registries.
2. Research maintained novel/manga translation tools and all relevant licenses.
3. Record concise research and architecture decisions.
4. Scaffold the repository and implement orchestration, Mock/TXT, CLI/API, Web, then the real
   manga Adapter.
5. Complete automation, deployment validation, open-source documents, and final acceptance.

Do not ask the user to choose ordinary technical options. Evaluate them, document tradeoffs, and
report real blockers instead of fabricating completion.
