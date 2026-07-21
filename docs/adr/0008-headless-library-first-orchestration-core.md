# ADR 0008: Headless, library-first orchestration core

- Date: 2026-07-21
- Status: Accepted

## Context

v0.1.0 and v0.2.0 proved TXT, EPUB 2/3, and manga translation through a persistent local
Project/Job/Artifact application. They also bundled a browser GUI, CLI, HTTP server, SQLite,
SQLAlchemy, and network clients into the default installation. That made embedding the useful
translation behavior require application infrastructure and made `import linguaspindle` an
unnecessarily broad dependency boundary.

The next integration consumers need deterministic document and manga translation primitives,
stable Segment/page identities, caller-controlled I/O, and normalized orchestration behavior.
They do not need LinguaSpindle to own a reader, editor, bookshelf, approval workflow, or other
calling-product state.

“Headless” therefore means removing the GUI and caller-side product concerns. It does not mean
removing manga, EPUB structure preservation, retry/cancellation, or the optional persistent Job
runtime.

## Decision

1. The default package is a side-effect-free Python library. Importing `linguaspindle` does not
   read environment variables, create directories, open SQLite, or start a worker thread.
2. The pure core accepts caller-owned paths, binary streams, or bytes and returns typed contracts.
   It owns TXT/EPUB inspection and reconstruction, manga image/CBZ processing, deterministic
   orchestration, bounded retry, events, cooperative cancellation, partial results, and stable
   errors. It imports no FastAPI, Uvicorn, Typer, SQLAlchemy, or Playwright.
3. TXT, common valid unencrypted EPUB 2/3, CBZ/ZIP, and single-image manga remain first-class
   product capabilities. Provider text translation and Manga Adapter image translation remain
   distinct protocols because their requests, results, health, and capability declarations are
   materially different.
4. `Segment`, `SegmentLocator`, `DocumentManifest`, `MangaPage`, and `MangaManifest` are the
   integration contracts. IDs and order are deterministic for an unchanged source and operation
   policy. Versioned JSON-compatible results support caller persistence and later reconstruction.
5. The caller owns output paths/streams and higher-level business state. LinguaSpindle does not
   provide a GUI, reader, proofreading UI, revision/approval history, bookshelf, content manager,
   user system, or caller Project model.
6. Provider credentials are supplied by the caller at runtime, either directly or through a key
   resolver. Only optional CLI/server configuration adapters read LinguaSpindle environment
   variables. Credentials never enter core model serialization, events, logs, errors, or output.
7. SQLite, the Artifact store, persistent Project/Job/Step recovery, CLI, and FastAPI server are
   optional layers. Their dependency direction is interfaces → optional runtime → pure core.
   Interfaces may also call the pure core directly. `JobRunner` starts only when a caller opts in.
8. The browser GUI, its static assets, Playwright/browser acceptance, and GUI routes are removed.
   The optional HTTP server is JSON/OpenAPI-only and retains the loopback-default trust boundary.
9. Migration `0003_headless_core.sql` adds a nullable stable Segment key and a partial per-Job
   uniqueness index. Existing v0.2.0 novel and manga rows and Artifact payloads remain in place;
   no old manga data is deleted and no new data root is required.
10. Optional dependency groups isolate OpenAI-compatible HTTP, the real manga HTTP Adapter,
    persistence, CLI, and server support. Mock Provider and Mock Manga Adapter remain available in
    the default installation without network, model, font, GPU, database, or server dependencies.

## Relationship to earlier decisions

- ADR 0001 remains authoritative for the permanent no-user-system and loopback-default trust
  boundary. Its references to opening a GUI no longer apply because v0.3.0 has no GUI.
- ADR 0002 remains authoritative for standalone operation, one implementation of business
  behavior, and independence from `novel-platform`. This ADR replaces its GUI-centric concrete
  interface set and makes the pure public core, rather than a persistent application service, the
  shared implementation boundary.
- ADR 0003 remains authoritative for capability-selected Adapters, immutable sources, typed
  provenance, and keeping upstream tools outside the repository. Artifact identities are an
  optional-runtime persistence mechanism; the pure core uses caller-owned streams/bytes without
  exposing storage paths as durable identities.
- ADR 0004 remains authoritative only for the optional local runtime: Python, SQLite, forward-only
  migrations, local Artifacts, and a durable in-process runner. Its mandatory FastAPI/Typer/
  SQLAlchemy default stack and browser application are replaced by optional extras and no GUI.
- ADR 0005's non-persistence and redaction boundary remains. Its fixed environment-only key source
  is replaced by caller injection; environment lookup belongs only to optional interfaces.
- ADR 0006 remains accepted without change: `manga-image-translator` is still a separately
  operated HTTP service with no vendored source, models, fonts, or GPU runtime.
- ADR 0007 remains accepted for structure-preserving EPUB reconstruction and bounded archive
  processing. Explicit `ArchiveLimits` replace mandatory global `Settings` in the pure API.

## Consequences

- Embedders can translate TXT, EPUB, images, and CBZ without constructing a Project, Job,
  database, or Artifact store.
- Selected Segment translation and caller-supplied/manual text are supported without introducing
  editorial workflow states into the engine.
- Durable Job recovery remains available but is no longer the only public API or a default
  dependency.
- The server root is machine-readable and no longer serves a product UI. Any reader/editor is a
  separate caller that consumes public manifests and results.
- Isolated installation tests are required for the default core and every supported extra.
