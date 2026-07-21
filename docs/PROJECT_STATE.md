# Project state

Last reviewed against the v0.3.0 execution contract and the current working implementation on
2026-07-21. The active milestone is the v0.3.0 headless/library-first refactor. Development is
based on the released v0.2.0 commit `b0b5ef20dff65e7ecb6ace495a82fbe855e5d930` without moving or
rewriting its tag. Mandatory source, static-analysis, migration, and local runtime gates passed;
package metadata is now `0.3.0` so the exact final Wheel, image, extras, and checksummed archive can
be verified before any publication decision.

## Current milestone direction

LinguaSpindle is becoming a headless, embeddable translation orchestration engine. The pure
Python core is now the primary implementation boundary; optional persistence and interfaces sit
above it. Removing the browser GUI does not remove TXT, EPUB, or manga translation.

The permanent boundaries remain: no user/account/identity/tenant/permission model; no
`novel-platform` dependency; immutable input; caller-controlled output; runtime-only Provider
secrets; capability-selected external Adapters; loopback-default HTTP; and no upstream manga
source/model/font/GPU redistribution.

## Implemented v0.3.0 candidate surface

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

v0.3.0 is a development candidate, not a published release. Command-level results, package
matrices, samples, dependency inventories, external-test classifications, and checksums are owned
by the versioned `acceptance/v0.3.0/` archive. This maintained state file must be updated with the
final conclusion only after that archive is complete; it does not substitute for or pre-judge the
acceptance report.

Required gates include core import/isolation, Python API and serialization, selected/manual TXT
and EPUB behavior, EPUB security/structure regression, image/CBZ partial/cancellation behavior,
fake real-Adapter protocol mapping, v0.2 data migration, isolated extras, Wheel/image contents,
Ruff, strict mypy, compileall, branch coverage, Python 3.11–3.14 CI, and available platform/
container checks.

Real paid Provider execution, real external manga model execution, external `epubcheck`, and
platforms unavailable to the acceptance environment must remain separately labeled optional
external tests. Mocks/fake HTTP services cannot be reported as real model runs.

No v0.3.0 tag, remote push, GitHub Release, or deployment is part of the current development
authority.

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
round trip.

Update this file when an implemented capability, verification conclusion, package/deployment
surface, limitation, or milestone state changes. Put target requirements in `PRODUCT_SPEC.md`,
rationale in ADRs, navigation in `MODULE_MAP.md`, and exact evidence under `acceptance/`.
