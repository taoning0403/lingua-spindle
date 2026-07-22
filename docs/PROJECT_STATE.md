# Project state

Last reviewed against the v0.3.1 service-hardening execution contract and current implementation
on 2026-07-22. Development started from refreshed `origin/main` commit
`25357315877a51e421891db945f3e8e485fd559b`; the published annotated `v0.3.0` tag still resolves to
`77974cbf47de2d40ac923e399c631056902b9f70` and its historical acceptance archive is unchanged.
Package/image metadata is now the local v0.3.1 candidate. No v0.3.1 branch/tag has been pushed,
no GitHub Release or package/image publication has occurred, and no server deployment has begun.

## Current milestone direction

LinguaSpindle is becoming a headless, embeddable translation orchestration engine. The pure
Python core is now the primary implementation boundary; optional persistence and interfaces sit
above it. Removing the browser GUI does not remove TXT, EPUB, or manga translation.

The permanent boundaries remain: no user/account/identity/tenant/permission model; no
`novel-platform` dependency; immutable input; caller-controlled output; runtime-only Provider
secrets; capability-selected external Adapters; loopback-default HTTP; and no upstream manga
source/model/font/GPU redistribution.

## Implemented v0.3.1 release surface

### Service idempotency and correlation

- The six persistent or Provider-triggering POST operations support a validated, immediately
  hashed `Idempotency-Key`; compatibility mode is default and opt-in required mode returns 428.
- Migration `0004_service_idempotency.sql` adds durable operation claims, nullable Job
  fingerprint/request ID fields, and a partial unique index for equivalent active Jobs.
- Same-key/same-request replays retain resource identity; changed, in-progress, and indeterminate
  requests use stable 409 error codes. Selected translation, rebuild, retry, Profile, Job, and
  streaming Project creation are covered without moving persistence concerns into the pure core.
- Equivalent active Jobs coalesce through SQLite across concurrent application instances.
  Terminal Jobs release the slot; Project publication is transactionally paired with its claim
  and removes concurrent-loser staging payloads.
- Every HTTP response includes a safe `X-Request-ID`; Job and Step evidence retains first-request
  correlation. Raw idempotency keys and Provider keys are never persisted or logged.

### Pure public core

- Side-effect-free top-level package exports for typed document and manga operations. Importing
  the package itself does not resolve Settings, create a data root, open SQLite, or start a worker.
- Public document calls: `inspect_document`, `extract_segments`, `translate_segments`,
  `rebuild_document`, and `translate_document`.
- Public manga calls: `inspect_manga`, `extract_manga_pages`, `translate_manga`, and
  `build_manga_output`.
- Dataclass/Protocol/Enum contracts for manifests, Segments/locators, pages, Provider and Adapter
  calls, options, events, cancellation, records, partial results, build results, and stable errors.
- Versioned JSON-compatible serialization/recovery for persistent manifests and result types.
- Explicit per-operation `TranslationOptions` and `ArchiveLimits`; no global runtime Settings in
  the pure API.

### TXT and selected translation

- Bounded TXT reads, BOM/UTF-8/charset detection, binary/empty rejection, newline inspection,
  deterministic segmentation, typed source spans, content roles, source/input hashes, and stable
  Segment IDs.
- Explicit all/selected/empty selection semantics, unknown-ID validation before Provider calls,
  caller-supplied/manual translation precedence, deterministic result order under concurrency,
  bounded retry, per-Segment errors, partial success, events, cancellation, and redaction.
- Rebuild from original spans so unmapped text and separators remain. The documented output
  contract is UTF-8 with LF newlines.

### EPUB 2/3

- The v0.2.0 structure-preserving inspector/rebuilder is exposed through the public document API.
- Common valid unencrypted EPUB 2/3 package/resource/reference checks, bounded archive handling,
  stable visible-text XML-slot locators, documented Ruby/navigation/metadata policy, immutable-
  source reconstruction, source fallback, target-language updates, independent output reopen/
  reinspection, unchanged-member comparison, and overwrite protection remain.
- Public manifests contain typed summaries/Segments plus an explicitly versioned opaque EPUB
  structure payload consumed by the accepted rebuilder.

### Manga

- Pure inspection for PNG/JPEG/WebP and CBZ/ZIP with stable page IDs, natural ordering, signature
  validation, safe paths, duplicate/symlink/encryption/compression checks, and explicit archive
  limits.
- Synchronous page orchestration with bounded retry, normalized/redacted page errors/logs/raw
  results, partial page retention, page-boundary cancellation, and image/CBZ output.
- Default `MockMangaAdapter` and the distinct `MangaTranslationAdapter` protocol remain in the
  core. The existing `manga-image-translator` implementation remains an optional HTTPX Adapter
  with explicit connection configuration and no bundled upstream assets.

### Optional integrations

- Default dependencies are limited to core TXT/EPUB needs. Extras isolate `openai`, `manga`,
  `runtime`, `cli`, `server`, and `all` dependencies.
- OpenAI-compatible configuration accepts a caller-supplied key or key resolver. Environment
  lookup is an optional CLI/server concern, not core behavior.
- `LocalRuntime` names the optional v0.2-compatible SQLite/Artifact/Project/Job facade.
  Construction opens configured persistence but does not start `JobRunner` automatically.
- Migration `0003_headless_core.sql` adds a nullable stable Segment key and partial per-Job unique
  index while retaining older TXT, EPUB, and manga records.
- The optional CLI imports runtime/server modules only for commands that use them and includes
  core document/manga inspect/Mock-translate/output-validate commands.
- The optional FastAPI server is headless JSON/OpenAPI. The old static GUI directory, root asset
  routes, SPA fallback, GUI tests, and browser dependency are removed; `/` is a compact service
  descriptor.

## Historical v0.2.0 baseline

v0.2.0 remains the immutable release/compatibility baseline. Its final archive records 23 Pass,
0 Fail, 0 Blocked; 149 default tests passed with 3 explicit skips and 83% branch-aware coverage;
and its checksums were verified before starting this branch. Historical statements in
`acceptance/v0.2.0/` describe the execution point at which they were captured and are not edited
to reflect later publication.

The v0.2.0 accepted behavior remains the regression target for TXT, structure-preserving EPUB 2/3,
image/CBZ manga, Mock and real-protocol integrations, controls/recovery, Artifact integrity,
archive safety, and secret handling. GUI/browser behavior is intentionally not a v0.3.0
regression target.

## Verification and release state

v0.3.0 remains accepted and published as an annotated Git tag. The versioned `acceptance/v0.3.0/`
archive binds its final results to source candidate
`84270dec38b5f92fcc044b36c170f4230c15170f` and records 20 Pass, 0 Fail, 0 Blocked, and
0 Not executed across required gates. The complete automated suite reports 228 passed,
0 skipped, and 83% branch-aware coverage; Ruff, strict mypy, compileall, and Compose parsing pass.

The exact 121,583-byte v0.3.0 Wheel passed isolated `core`, `openai`, `manga`, `runtime`, `cli`,
`server`, and `all` installation/`pip check`/offline smoke environments. Its default core depends
only on charset-normalizer and contains no GUI/browser resources. The Linux/arm64 acceptance image
runs as UID/GID 10001 with a read-only root and passed hardened live root/health probes. Historical
v0.2.0 checksums and refs remain unchanged.

Real paid Provider execution, real external manga model execution, external `epubcheck`, native
Windows/WSL2, and Python 3.11/3.13/3.14 hosts are explicitly recorded as optional external tests
not executed in this local run. Mocks/fake HTTP services are not reported as real model runs.

The `codex/v0.3.0-headless-core` branch, annotated `v0.3.0` tag, and `main` release commit were
pushed on 2026-07-21. No GitHub Release or deployment was performed; those remain separate future
actions.

The local v0.3.1 acceptance archive binds all executable gates to clean source candidate
`1d5949437bbbbd0bdbeb1a86d407832dd2d28c3c` and records 18 Pass, 0 Fail, 0 Blocked, and
0 Not executed across required gates. The complete suite reports 248 passed, 0 skipped, and 84%
branch-aware coverage; focused migration, idempotency, and security suites also pass.

The exact 132,544-byte v0.3.1 Wheel has SHA-256
`44ef868324c1f2d24868c3fe3efb8f4b443f0954d2dde9f4a386d05995fb5976` and passed all seven
isolated extras environments. Migration 0004, compatibility/required idempotency modes, two-
instance SQLite concurrency, Provider/Idempotency key containment, Compose parsing, and
deterministic samples pass. The Linux/arm64 image digest is
`sha256:0b0a0b7f0df9dbbd5ef19810835ed6aef45c8ad1f8b4cabf3c66e6be3d9e85ba`; live health,
UID/GID 10001, read-only root, Volume/tmpfs, no-new-privileges, loopback publish, forced 428, and
Request ID behavior pass. Temporary container/Volume resources were removed.

Real paid Provider execution, real external manga model execution, external `epubcheck`, native
Windows/WSL2, and Python 3.11/3.13/3.14 hosts remain explicit optional external tests not executed.
Remote CI is not executed because the branch was not pushed. No v0.3.1 push, tag, merge, GitHub
Release, Wheel/image publication, or deployment has occurred; publication remains blocked on
explicit user approval and a later green target-commit CI run.

## Upgrade/deployment state

- A core-only installation owns no mutable data root.
- Optional runtime users stop writes and back up the entire v0.2.0 data root before first v0.3.0
  startup. Migrations are forward-only; rollback restores that complete backup and v0.2.0.
- Existing manga Projects/Jobs/Artifacts are retained. Migration 0003 does not backfill or delete
  their data.
- The optional server remains loopback-default. Compose maps only host `127.0.0.1` by default and
  uses the server/all extras; it serves no GUI.
- The container remains non-root with a read-only root under Compose, a persistent `/data`, and no
  external manga stack, model, font, GPU runtime, browser, or paid key.
- v0.3.0 optional-runtime users stop all writers and back up the complete data root/Volume before
  migration 0004. Existing rows remain valid with nullable Job fields; rollback restores the
  complete pre-upgrade backup rather than downgrading schema 4 in place.

## Known limitations and deliberate omissions

- Novel formats remain TXT and common valid unencrypted EPUB 2/3. No PDF, DOCX, MOBI, AZW3, DRM
  bypass, browser-rendered book content, or broad invalid-publisher repair.
- The pure core API is synchronous. Callers choose threads, tasks, queues, and scheduling.
- The optional runtime remains one host, SQLite, and a local Artifact store; no broker,
  distributed worker, object store, or general DAG editor.
- The current real manga Adapter has no streaming internal progress or immediate mid-image
  cancellation. The boundary is one page call.
- No GUI, reader, proofreading/review UI, revision/approval history, business bookshelf/project
  model, CAT editor, translation-memory product, bubble-level manga editing, or plugin market.
- Modified EPUB XML may differ in insignificant serialization details; package semantics,
  references, and intentionally unmodified member bytes are the validation boundary.

## Decisions and update triggers

ADR 0008 owns the library-first/headless dependency direction and supersedes the GUI/default-
framework/key-source details of ADRs 0002, 0004, and 0005. ADRs 0001, 0003, 0006, and 0007 remain
authoritative for trust, immutable/capability boundaries, the external manga service, and EPUB
round trip. ADR 0009 owns server idempotency, active Job coalescing, and request correlation while
keeping those concerns out of the pure core.

Update this file when an implemented capability, verification conclusion, package/deployment
surface, limitation, or milestone state changes. Put target requirements in `PRODUCT_SPEC.md`,
rationale in ADRs, navigation in `MODULE_MAP.md`, and exact evidence under `acceptance/`.
