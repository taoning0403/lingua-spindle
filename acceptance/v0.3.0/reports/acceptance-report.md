# LinguaSpindle v0.3.0 acceptance report

> **Final status: Pass / release pending.** All mandatory executable gates available in the
> acceptance environment passed for source candidate
> `84270dec38b5f92fcc044b36c170f4230c15170f`. Optional external tests are reported separately
> and are not represented by mocks.

- Report date: 2026-07-21 (Asia/Shanghai)
- Branch: `codex/v0.3.0-headless-core`
- Source candidate: `84270dec38b5f92fcc044b36c170f4230c15170f`
- Host: macOS 26.5.2 / Darwin 25.5.0, arm64, Python 3.12.11
- Container: Docker 29.6.1, Linux/arm64
- Package version: `0.3.0`
- Test policy: deterministic offline Mock Provider and Mock Manga Adapter by default

The commit containing this archive adds evidence and the final maintained project-state conclusion
only. The source candidate above is the exact clean revision used for the final static checks,
test suite, Wheel build, isolated extras matrix, and Docker image build.

## Conclusion

v0.3.0 completes the requested pure headless refactor without removing translation capability.
The default installation is an embeddable, side-effect-free core for TXT, common valid unencrypted
EPUB 2/3, single images, and CBZ/ZIP. Persistence, CLI, FastAPI/Uvicorn, SQLAlchemy, Typer, and
HTTPX integrations are optional extras. The Web GUI, static HTML/JavaScript/CSS, SPA fallback,
Playwright, browser tests, screenshots, and browser traces are removed.

The public core exposes typed manifests, stable Segment/page identities, Provider and Manga
Adapter protocols, selected/manual translation, immutable-source reconstruction, retry,
concurrency, progress events, cancellation, partial results, normalized errors, and versioned
JSON-compatible DTOs. Provider and Manga Adapter contracts remain deliberately distinct.

The exact Wheel installed successfully in seven isolated environments: core, openai, manga,
runtime, cli, server, and all. Every `pip check` and offline smoke passed. The core-only environment
contained only LinguaSpindle, charset-normalizer, and pip; server/database/CLI/browser modules were
absent. The Wheel contains migrations 0001–0003 and no Web, HTML, CSS, JavaScript, Playwright,
upstream manga source, model, or font resource.

The complete automated suite passed: **228 passed**, **0 skipped**, **83% branch-aware coverage**.
Ruff formatting/lint, strict mypy, compileall, and Compose configuration passed. A Linux/arm64
image ran as UID/GID 10001 with a read-only root, no external network, dropped capabilities, and
`no-new-privileges`; live `/` and `/health` returned version 0.3.0 and database status `ok`.

## Required acceptance matrix

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| A01 | Preserve the published v0.2.0 baseline and historical archive | Pass | All v0.2.0 checksums pass; its tag and `origin/main` still resolve to `b0b5ef20dff65e7ecb6ace495a82fbe855e5d930`; no historical file changed. |
| A02 | Side-effect-free core import with minimal default dependencies | Pass | Fresh-process import evidence and isolated `core` extra smoke show no environment/data-root/database/thread side effects and no optional modules loaded. |
| A03 | Typed public core, serialization, events, cancellation, and stable errors | Pass | Core and DTO tests cover every public manifest/result, schema version, caller protocols, progress, retries, callback boundaries, and secret-safe errors. |
| A04 | TXT inspection, stable segmentation, selection/manual mapping, and rebuild | Pass | Tests and retained samples cover encoding/newlines, binary disguise, bounds, stable IDs, empty/unknown selection, manual text, concurrency, partial failure, one-shot streams, and immutable output. |
| A05 | EPUB 2/3 structure-preserving public core | Pass | Tests and retained EPUB2/3 samples cover package/navigation/resources/locators, Mock translation, target language, reopen/reimport, source mismatch, unchanged resources, and safe archive limits. |
| A06 | Image and CBZ/ZIP manga core | Pass | Tests and retained image/CBZ samples cover natural order, valid output, partial pages, raw results/logs, archive safety, format validation, and source/manifest integrity. |
| A07 | Provider and Manga Adapter orchestration semantics | Pass | Bounded retry/backoff, deterministic ordering, usage/attempts, partial success, pre-cancellation, page-boundary cancellation, one health probe per runtime Step, and no fabricated streaming progress pass. |
| A08 | Credential and sensitive-value containment | Pass | Tests reject Provider success payloads that echo protected values and scan persisted/public data; Adapter metadata/log/error redaction and key resolver behavior pass. |
| A09 | Optional dependency boundaries and diagnostics | Pass | Core-only imports remain functional; missing optional surfaces identify `[openai]`, `[manga]`, `[runtime]`, `[cli]`, or `[server]`; all installed extras load their intended entry points. |
| A10 | Headless CLI and HTTP interfaces reuse public core/runtime | Pass | API/CLI integration and OpenAPI tests pass; root is JSON, GUI/static/SPA routes are absent, and Segment selection/caller-mapping rebuild are exposed. |
| A11 | Optional local runtime and explicit worker lifecycle | Pass | SQLite/Artifact/Project/Job recovery tests pass; construction does not start a worker; runtime maps durable records to core DTOs. |
| A12 | Non-destructive v0.2.0 data migration | Pass | Real v0.2.0 Wheel-created TXT/EPUB/manga roots migrate through 0003; complete and partial successes, Projects, Jobs, Steps, Segments, and Artifacts remain usable. |
| A13 | Exact v0.3.0 Wheel identity and contents | Pass | `linguaspindle-0.3.0-py3-none-any.whl`, 121,583 bytes, SHA-256 `9b8f2eb8ebf5d9ff17cbde8e9caceb4dc0dfc44fdb6fcf73c828a6292258bd48`; no GUI/browser resources; migrations 0001–0003 present. |
| A14 | Isolated core and extras installation matrix | Pass | Seven of seven environments passed install, `pip check`, dependency inventory, and offline smoke; report is bound to the exact Wheel and clean candidate SHA. |
| A15 | Non-root headless Docker image and live health | Pass | Image digest `sha256:f757c6c5430562632b7bcfdd57c4094735840db70a50312e11394c15d35d9b1e`, 61,012,787 bytes; UID/GID 10001, read-only root, no network, no GUI files, live root/health pass. |
| A16 | Formatting, lint, typing, compilation, and Compose configuration | Pass | Ruff 0.15.22 format/check, mypy 1.20.2 strict check, Python compileall, and Docker Compose 5.3.0 configuration all exited zero. |
| A17 | Complete automated suite and branch coverage | Pass | Pytest 8.4.2: 228 passed, 0 skipped; total branch-aware coverage 83%; no acceptance threshold was weakened. |
| A18 | Deterministic retained TXT/EPUB/manga samples | Pass | Generator produced 27 checksummed files with Mock-only translation, manifests/results, output reopen/validation, and import-boundary evidence. |
| A19 | Product, architecture, security, licensing, and migration documentation | Pass | ADR 0008, public API, CLI/API/Docker/install, migration, release, module, data-model, product, security, and third-party documents match the implementation. |
| A20 | Complete versioned acceptance archive | Pass | Required report, machine evidence, command log, environment, Wheel, samples, extras/dependency evidence, and recursive SHA-256 inventory are present and verify. |

Required result: **20 Pass, 0 Fail, 0 Blocked, 0 Not executed**.

## Public Python API

Novel operations:

```text
inspect_document
extract_segments
translate_segments
rebuild_document
translate_document
inspect_epub
build_translated_epub
```

Manga operations:

```text
inspect_manga
extract_manga_pages
translate_manga
build_manga_output
```

Key public contracts include `DocumentManifest`, `Segment`, `SegmentLocator`, `MangaManifest`,
`MangaPage`, `TranslationProvider`, `TranslationRequest`, `TranslationRecord`,
`TranslationBatchResult`, `MangaTranslationAdapter`, `MangaTranslationResult`,
`TranslationOptions`, `TranslationEvent`, `CancellationToken`, `BuildResult`, `ArchiveLimits`,
`LinguaError`, and `ErrorCode`.

## Dependency and package boundary

The v0.2.0 default installation directly required charset-normalizer, FastAPI, HTTPX,
platformdirs, Pydantic, python-multipart, SQLAlchemy, Typer, and Uvicorn, and its package data
contained Web assets. v0.3.0 defaults to only `charset-normalizer>=3.4,<4`.

Optional groups now own HTTP Provider (`openai`), external manga HTTP Adapter (`manga`),
SQLite/Artifact runtime (`runtime`), Typer commands (`cli`), FastAPI/Uvicorn (`server`), and the
combined surface (`all`). The `dev` group adds validation tools but no browser dependency.

## GUI removal and retained capabilities

Removed: `src/linguaspindle/web/`, static package data, GUI routes/text, SPA fallback, Playwright,
browser markers/tests, screenshots, traces, and JavaScript/Node gates. No replacement frontend or
reader was introduced.

Retained: TXT, EPUB 2/3, image, CBZ/ZIP, Mock Provider, Mock Manga Adapter, OpenAI-compatible
Provider, existing `manga-image-translator` HTTP protocol, runtime Pipelines, retry/cancel/progress,
partial results, Artifact downloads, diagnostics, CLI, and headless JSON/OpenAPI.

## v0.2.0 migration

The pure core owns no data root. Optional runtime users must stop writes and back up the complete
v0.2.0 root before first v0.3.0 startup. Forward-only migration 0003 adds nullable stable Segment
keys and an index; it does not delete or rewrite old novel/manga rows or Artifact payloads.
Rollback restores the complete backup and v0.2.0 software. The full procedure is documented in
`docs/migrations/v0.2-to-v0.3.md`.

## Optional external tests

| Category | Test | Status | Reason / next action |
| --- | --- | --- | --- |
| Optional external test | Real paid OpenAI-compatible Provider | Not executed | No paid credential or cost was authorized. Use a disposable key only under explicit authorization. |
| Optional external test | Real `manga-image-translator` model service | Not executed | External model/font/GPU operation remains separately deployed and licensed; fake HTTP coverage is not called a real model run. |
| Optional external test | External `epubcheck` | Not executed | Built-in package/reference/reopen validation passed; external certification remains optional. |
| Optional external test | Native Windows/WSL2 | Not executed | This run covered macOS arm64 and Linux/arm64 Docker; CI contains a Windows core job. |
| Optional external test | Python 3.11, 3.13, and 3.14 hosts | Not executed | This host ran 3.12.11; CI declares 3.11–3.14 and must provide supplemental remote evidence when executed. |

Optional result: **0 Pass, 0 Fail, 0 Blocked, 5 Not executed**. These unavailable/external tests
do not change the local acceptance conclusion, and no Mock/fake result is mislabeled.

## Known limitations

- Inputs remain TXT, common valid unencrypted EPUB 2/3, image, and CBZ/ZIP only.
- EPUB support does not bypass DRM or broadly repair invalid publisher files.
- Manga output is whole-page; there is no bubble/region editing or immediate mid-call cancellation.
- The pure API is synchronous; callers choose their own thread/task/queue model.
- The optional runtime remains single-host SQLite/local Artifact storage, not a distributed queue.
- There is no GUI, reader, proofreader, revision/approval system, user system, business bookshelf,
  CAT editor, translation-memory product, or plugin marketplace.

## Harness corrections and environment limits

The first isolated Wheel build could not reach the package index inside the filesystem/network
sandbox; the exact command was rerun with approved network access and passed. Initial Docker
access was denied by the sandbox and passed after approved daemon access. A first content scan
used the substring `.js` and falsely matched `direct_url.json`; an exact suffix scan passed. A
first hardened server probe mounted `/data` as a root-owned tmpfs, so the non-root process correctly
could not create its database. The corrected tmpfs used UID/GID 10001 and mode 0750; the image then
became healthy. These were harness/environment corrections, not product-source changes.

## Publication state

- Remote branch push: **Not executed by instruction**
- v0.3.0 tag creation/push: **Not executed by instruction**
- GitHub Release: **Not executed by instruction**
- Deployment: **Not executed**
- Release state: **release pending**

Publication requires separate authorization after this archive is reviewed.
