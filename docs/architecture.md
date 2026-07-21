# Architecture

LinguaSpindle v0.3.0 is a Python modular monolith with a pure, synchronous translation core and
optional persistence/interfaces. “Headless” removes the browser product surface and caller-side
business workflow; TXT, EPUB, and manga remain formal engine capabilities.

## Dependency rule

```text
optional interfaces
  Typer CLI / FastAPI JSON server
                 |
optional local runtime
  ApplicationService/LocalRuntime / SQLite / Artifact store / JobRunner
                 |
pure public core
  typed models / I/O / TXT / EPUB / manga / orchestration
        /                              \
TranslationProvider              MangaTranslationAdapter
```

Dependencies point downward only. The core does not import optional interfaces/runtime or their
frameworks. It receives explicit values for the current call and does not resolve environment
variables or global Settings.

Top-level `import linguaspindle` exports the public core, Mock Provider, and Mock Manga Adapter.
It performs no filesystem, database, network, environment, or worker action. Explicit operations
may read caller input and write only to caller-supplied output.

## Pure public core

### Typed contracts

`core/models.py` defines immutable dataclasses and Enums for document manifests, stable Segments/
locators, manga pages/manifests, translation options/records/batches, events, cancellation, page
results, and build results. Provider and Manga Adapter are runtime-checkable Protocols in their
respective modules. Public persistent payloads carry an explicit schema version and reject unknown
versions during recovery.

Core models contain no SQLAlchemy objects, Project/Job identity, Artifact storage key, secret,
global data path, or calling-product review state. `DocumentManifest.structure` is a documented,
versioned opaque EPUB compatibility payload used by the already accepted rebuilder; typed
Segments and metadata are the stable integration surface.

### Caller-owned I/O

Core input is a path/path-like object, binary stream, or bounded bytes value. Output is an explicit
path/path-like object or binary stream. Path output is atomically replaced only when the caller
sets `overwrite=True`; document output may never resolve to the immutable source path.

Path/stream/bytes values are transport, not persistent identity. `source_sha256`, source size,
stable Segment/page IDs, locators, and schema versions bind saved results to source content. A
rebuild with a mismatched source fails before publication.

### Document flow

```text
caller source
  -> bounded read + TXT/EPUB detection
  -> inspect_document -> DocumentManifest + ordered Segment tuple
  -> translate_segments (selected/all/none, existing/manual precedence)
  -> TranslationBatchResult
  -> rebuild_document from the same immutable source
  -> caller output + BuildResult
```

`translate_document` composes those same calls; it is not a second implementation.

TXT decoding and segmentation live in `core/txt.py`. Segments use deterministic source offsets,
content roles, hashes, and preserved source gaps. Rebuild substitutes only successful/manual
text, retains all other spans, then emits UTF-8/LF.

EPUB processing delegates archive/package/XML mechanics to dependency-light `epub.py`. Inspection
checks package structure and extracts ordered visible text into stable XML-slot locators. Rebuild
starts from the immutable ZIP, modifies declared slots and language metadata, preserves unmapped
source text and unmodified resources, then independently reopens/reinspects and validates output.
Explicit `ArchiveLimits` control member count, total/per-member expansion, compression ratio, and
path depth.

### Novel orchestration

`translate_segments` is synchronous and persistence-free. `selected_segment_ids=None` selects all;
an explicit empty iterable selects none. It rejects unknown selected/existing IDs before calling
the Provider. Existing successful or caller-authored translations take precedence.

The core owns deterministic final order, bounded concurrency, bounded exponential retry, attempt
and usage normalization, retryable/terminal classification, progress events, cooperative
cancellation, partial results, and redaction. A caller decides whether to run this synchronous
operation in a thread/task/queue and where to persist returned records.

### Manga flow

```text
caller image/CBZ
  -> bounded read + image signature / safe archive inspection
  -> MangaManifest + stable naturally ordered pages
  -> translate_manga through MangaTranslationAdapter
  -> page images + normalized raw/log/error results
  -> build_manga_output
  -> caller image/CBZ + BuildResult
```

Image and CBZ input is validated before Adapter calls. Successful page outputs remain when another
page fails. Cancellation is checked between page calls. The core does not claim mid-image
cancellation or streaming internal progress from an Adapter that does not provide it.

## Provider and Manga Adapter boundaries

Text Providers and Manga Adapters deliberately remain different contracts:

- `TranslationProvider.translate(TranslationRequest)` returns text/model/usage for one Segment.
- `MangaTranslationAdapter` declares a capability manifest and health result, then translates one
  image into an image plus raw metadata.

Both are caller-implementable and use shared orchestration semantics, but their health,
capabilities, request fields, and binary/text outputs cannot be made one meaningful method.

The deterministic Mock implementations are default core components. The optional
OpenAI-compatible Provider uses HTTPX and accepts an explicit key or key resolver. It makes one
transport attempt; core orchestration owns retries. Optional interface configuration may read
`LINGUASPINDLE_OPENAI_API_KEY`, but the core and serialized options do not.

The optional `manga-image-translator` Adapter calls a separately operated HTTP service. ADR 0006
remains authoritative: LinguaSpindle neither starts/downloads the upstream nor redistributes its
GPL source, models, fonts, container, or GPU runtime.

## Optional local runtime

`LocalRuntime` is the named facade over the v0.2-compatible `ApplicationService`. It opens the
configured SQLite database and Artifact store only when constructed. `JobRunner` is explicit and
does not start as a constructor/import side effect.

The runtime retains Projects, immutable Sources, Jobs, ordered StepRuns/logs, Segments, QA,
Profiles, Provider configuration, and Artifacts. Its responsibility is to:

- map database/Artifact records to public core inputs and DTOs;
- select a versioned TXT/EPUB/manga Preset;
- checkpoint Job/Step/Segment/page state at safe boundaries;
- map core events/errors/results back into durable state and Artifacts;
- claim queued Jobs conditionally and recover interrupted work; and
- expose use cases to optional interfaces without leaking SQLAlchemy models or storage paths.

The runtime remains a local one-host scheduler. It is not a second format engine, a distributed
queue, or a general DAG. Existing v0.2.0 records migrate forward through additive schema 0003.

### Job lifecycle

```text
queued -> running -> succeeded | partially_succeeded | failed
   |          |  \-> cancelling -> cancelled
   |          \----> paused -> queued
   \---------------------------> paused | cancelled
failed | partially_succeeded -> queued (explicit retry)
```

Step/segment/page boundaries are durable control points. A process exit classifies active work as
`PROCESS_INTERRUPTED`; successful prior boundaries stay reusable. An Adapter without immediate
cancellation may finish or time out its current image before the Job becomes cancelled.

## Persistence and Artifact boundary

All optional runtime mutable state is below one configured data root. SQLite stores small metadata
and structured records; payload bytes live under the private Artifact store. WAL, foreign keys, a
busy timeout, conditional claims, safe relative keys, checksums, and atomic payload publication
support one local process/host boundary.

Runtime imported Sources are copied once and never modified. Generated manifests, extracted text,
translations, page images, raw Adapter results, QA, and outputs receive Artifact identity,
checksum, media type, provenance, and safe storage location. Cross-runtime layers use Artifact IDs
and typed metadata rather than machine-specific paths. The runtime alone resolves a private
Artifact path at storage/Adapter boundaries.

Project deletion remains explicit and is rejected while a Job is non-terminal. Backups copy the
entire stopped data root so SQLite and payload identity remain consistent.

### Stable Segment migration

Migration 0003 adds nullable `translation_segments.segment_key` plus a partial unique index on
Job/key. New document rows can store the public stable Segment ID. Existing v0.2.0 rows remain
unchanged with a deterministic legacy key supplied at read time. The migration deletes no novel,
manga, or Artifact state.

## Optional CLI and HTTP

The console entry module can report a missing `[cli]` extra without importing Typer. Core document
and manga commands call public functions directly. Runtime and server modules are loaded only for
persistent or serve commands.

The FastAPI service is optional, typed, JSON/OpenAPI-only, and backed by the optional runtime for
long Jobs. It retains health/capability, Project/Job/control, Segment, Artifact/download, and
export surfaces, including caller-oriented selected translation/rebuild operations. It serves no
HTML, JavaScript, CSS, reader, editor, or SPA fallback. `/` returns a compact headless descriptor.

Interfaces normalize public errors but do not implement translation/rebuild algorithms or access
private core helpers/SQLAlchemy tables.

## Trust and secrets

There is no User, Account, Session, Role, Permission, Organization, Tenant, Membership, owner, or
creator. All optional runtime state belongs to one instance. Anyone with network access has full
instance capability.

Non-container server startup defaults to `127.0.0.1`. Compose publishes only host
`127.0.0.1` while the process binds inside its isolated container network. Remote operation needs
an explicit outer perimeter whose identity never enters LinguaSpindle.

Provider credentials are supplied at call/runtime configuration. Secret-shaped fields and known
runtime values are redacted before managed persistence. Raw Provider responses/headers are not
persisted. Imported user content receives content-safe exact-key scanning rather than deletion of
ordinary words such as “password” or “secret.” Archive output checks bounded expanded members.

## Errors and observability

`LinguaError`/`ErrorCode` are shared across the public core and optional layers. Stable codes cover
configuration/dependency, source/archive bounds, unsafe/invalid/protected EPUB, source mismatch,
unknown Segment, Adapter/provider availability, transport/model/rate errors, timeout,
cancellation, missing output, invalid state, interruption, storage, and unknown failures.

Core events report start, retry, success/failure, progress, cancellation, and completion. They are
synchronous notifications and contain no credential. Optional runtime logs persist redacted
evidence; interfaces render stable envelopes. Unsupported progress is never invented.

## Packaging and deployment

The default Wheel contains the pure core, mocks, and migrations but no static Web resources. Its
only direct runtime dependency is TXT charset detection. Optional extras provide HTTP clients,
persistence, CLI, or server frameworks. Playwright/browser binaries are not package or v0.3.0
acceptance dependencies.

The supplied container is a headless server/runtime deployment, not the default library. It runs
non-root, uses a read-only root under Compose, persists `/data`, bounds `/tmp`, and contains no
external manga stack, model, font, GPU runtime, browser, or paid key.

## Deliberate limits

- TXT and common valid unencrypted EPUB 2/3 novels; PNG/JPEG/WebP and CBZ/ZIP manga.
- One synchronous pure execution; embedding scheduling is caller-owned.
- Optional one-host SQLite/local-Artifact runtime only.
- No GUI, reader, proofreader, revision/approval workflow, caller bookshelf/content model, CAT
  editor, plugin market, distributed scheduler, PDF/DOCX/MOBI/AZW3, DRM bypass, or bubble-level
  manga editing.
- No streaming manga protocol or immediate mid-image cancellation in the current real Adapter.
