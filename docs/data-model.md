# Data model

v0.3.0 has two deliberately separate model sets:

1. pure public dataclasses for embedding and caller-owned serialization; and
2. optional private SQLAlchemy/SQLite records for the local persistent runtime.

SQLAlchemy models are not public core types. Using the pure library requires no Project, Job,
database, Artifact ID, or data root.

## Pure public contracts

```text
DocumentManifest 1 ── * Segment 1 ── 1 SegmentLocator
                         |
                         └── 0..1 TranslationRecord

TranslationBatchResult ── ordered TranslationRecords
DocumentTranslationResult ── manifest + batch + BuildResult

MangaManifest 1 ── * MangaPage
MangaTranslationResult ── manifest + ordered MangaPageTranslations
```

### DocumentManifest and Segment

`DocumentManifest` binds a bounded inspected source by SHA-256, byte size, detected format,
optional filename, and ordered Segments. TXT manifests also report encoding/confidence, newline
style, and segmentation version. EPUB manifests report typed package metadata and retain an
explicitly versioned opaque structure payload used by the structure-preserving rebuilder.

Every `Segment` contains:

- deterministic stable `segment_id` and source order;
- source format, document/chapter path, and original text;
- content role;
- typed TXT span or EPUB XML-slot `SegmentLocator`;
- source-text and complete translation-input hashes; and
- join/reconstruction information.

For unchanged source bytes and inspection/translation-input policy, ID and order remain stable.
The source SHA-256, size, IDs, and locators are checked before saved data is reused for extraction
or rebuild.

### Translation results

`TranslationRecord` binds one Segment ID/order/hash to source, succeeded, manual, failed, or
cancelled state. It may contain translated text, Provider/model, attempt count, normalized token
usage, and an `ErrorRecord`. It has no proofreading, approved, or published business state.

`TranslationBatchResult` preserves complete source order, explicit selected IDs, a batch status
(`succeeded`, `partially_succeeded`, `failed`, `cancelled`, or `noop`), and optional source hash.
Unselected source records and successful/manual caller records make later partial retries and
reconstruction deterministic.

`BuildResult` records format, output SHA-256/size, translated/preserved counts, and bounded
format-specific details. `DocumentTranslationResult` groups the manifest, batch, and build result.

### Manga models

`MangaManifest` binds an image or CBZ source by SHA-256/size and stores naturally ordered
`MangaPage` entries. Each page has stable ID, order, safe display/member name, media type, page
checksum, and size.

`MangaPageTranslation` records source page identity/order, succeeded/failed/cancelled state,
translated image/media type, attempts, redacted raw result, normalized logs, and optional error.
`MangaTranslationResult` groups the source manifest, ordered page results, batch status, and
Adapter ID. Successful pages remain present when another page fails.

### Versioned serialization

Persistent public aggregates carry schema strings such as `document-manifest.v1`,
`translation-batch.v1`, `document-translation.v1`, `manga-manifest.v1`,
`manga-translation.v1`, and `build-result.v1`. `to_dict`/`from_dict` values contain only
JSON-compatible data. Manga page images are base64 when binary inclusion is requested.

Unknown schema versions are rejected. These payloads are integration data, not an application
database or revision/approval history.

## Optional runtime relational model

SQLite migrations `0001_initial.sql`, `0002_epub.sql`, `0003_headless_core.sql`, and
`0004_service_idempotency.sql` implement the local runtime through private classes in
`src/linguaspindle/models.py`.

```text
LinguaSpindle instance
├── Project 1 ── * Source ── 1 immutable source Artifact
├── Project 1 ── * Job 1 ── * StepRun 1 ── * StepLog
│                         ├── ordered input/output Artifact IDs
│                         ├── * TranslationSegment
│                         └── * QaFinding
├── Project 1 ── * Artifact (optional Job/Step provenance)
├── TranslationProfile (instance-scoped, secret-free)
├── ProviderConfig (instance-scoped, secret-free)
└── IdempotencyRecord (operation-scoped, hashed key, safe resource reference)
```

There is no User, Account, Session, Role, Permission, Organization, Tenant, Membership, owner,
creator, or identity foreign key. All records belong directly to the one instance.

### Representation

- Domain IDs are UUID4 strings; StepLog/QaFinding use local integer sequence IDs.
- Timestamps are UTC datetimes serialized as ISO 8601.
- State strings are validated by explicit transition rules.
- Small metadata/configuration and ordered Artifact-ID links use sanitized JSON text.
- Large/immutable payload bytes stay outside SQLite.
- Forward-only versions are recorded in `schema_migrations` atomically.
- SQLite enables foreign keys, WAL, and a bounded busy timeout.

### Project and Source

`projects` retains instance-local name, novel/manga kind, language pair, and timestamps.
`sources` records TXT/EPUB/CBZ/image kind, original name, media type, byte size, checksum,
inspection metadata, and the immutable source Artifact. Import/re-import always creates another
Source/Artifact rather than changing payload bytes.

Project is an optional runtime grouping, not a public core or caller business-project contract.
Confirmed deletion is refused while related Jobs are non-terminal.

### Job, StepRun, and recovery

`jobs` stores Project/Profile/Pipeline/Provider/Adapter references, status/progress/control,
secret-free snapshots, claim token, nullable execution fingerprint/request ID, timestamps, and
normalized terminal error. `step_runs` stores
ordered capability/executor state, attempts, progress, Artifact links, configuration, and error;
`step_logs` is append-only across retry.

```text
queued -> running -> succeeded | partially_succeeded | failed
   |          |  \-> cancelling -> cancelled
   |          \----> paused -> queued
   \---------------------------> paused | cancelled
failed | partially_succeeded -> queued (explicit retry)
```

Core results are checkpointed at Segment/page and Step boundaries. An interrupted active Step is
marked `PROCESS_INTERRUPTED`; completed earlier Steps remain reusable. Constructing the runtime
does not start a worker.

### Artifact

`artifacts` stores required Project, optional Job/Step provenance, kind, safe filename, media type,
size, SHA-256, unique private relative storage key, redacted metadata, and creation time. Payload
publication is same-directory temporary write, `fsync`, and atomic replacement before the record
is exposed. A row failure removes its new payload.

Runtime Sources, manifests, extracted text, translations, QA, EPUB package/validation reports,
manga pages/raw outputs, and final TXT/JSON/EPUB/image/CBZ outputs are Artifacts. Interfaces return
Artifact IDs/downloads, never private storage keys or caller-controlled absolute paths.

### TranslationProfile and ProviderConfig

Profiles remain reusable non-secret translation policies: language pair, Provider/model, style,
context, prompt/version, batch, and model parameters. The word “profile” has no person/account
meaning. A Job snapshots policy to preserve history.

Provider configuration stores endpoint/model/timeout/concurrency/retry policy only. Credentials
are resolved at optional interface/runtime call time and have no column, serialized field, suffix,
or hash.

### TranslationSegment and migration 0003

`translation_segments` remains unique by Job and sequence and stores source/translation, status,
Provider/model/policy, error, timestamps, and EPUB source/document/role/locator/hash/reuse lineage.

Migration 0003 adds nullable `segment_key VARCHAR(64)` and a partial unique index on
`(job_id, segment_key)` for non-null values. New runtime document rows store the public stable
Segment ID there. Existing v0.2.0 rows remain `NULL`; the runtime derives a deterministic legacy
read key. No existing TXT, EPUB, manga, Job, or Artifact data is deleted or rewritten.

The primary internal row `id` remains a runtime UUID and is distinct from the stable public
`segment_id`. Clients use the latter for selected translation and reconstruction.

`qa_findings` remains diagnostic, not an editorial revision model.

### IdempotencyRecord and migration 0004

`idempotency_records` is unique on `(scope, key_hash)`. It stores only the SHA-256 of the raw
caller key, a versioned semantic request fingerprint, processing/completed/failed/indeterminate
state, safe resource type/ID/result reference, normalized error metadata, request ID, and
timestamps. It never stores the raw key, Provider key, uploaded source, or caller translation
text.

Migration 0004 also adds nullable `jobs.execution_fingerprint` and `jobs.request_id`. A partial
unique index on the execution fingerprint applies only to queued/running/paused/cancelling Jobs,
which coalesces equivalent active work and permits intentional reruns after terminal state.
Existing Jobs remain valid with `NULL` values and are not retroactively coalesced.

## Invariants

- Never mutate source bytes or rebuild to the source path.
- Validate saved manifest/source checksum and size before reuse/rebuild.
- Never silently reinterpret an empty selection as all Segments.
- Preserve caller-supplied successful/manual translations.
- Preserve source/page order independently of concurrent completion.
- Publish no successful output/Artifact for a missing or partial payload write.
- Pass public DTOs or runtime Artifact IDs across boundaries, never private absolute paths.
- Persist state before reporting it through an optional interface.
- Never repeat succeeded Steps unconditionally after restart.
- Never store or serialize a Provider key.
- Never store or log a raw Idempotency-Key; persist only its hash and safe correlation metadata.
- Let SQLite uniqueness and transactions arbitrate concurrent idempotency/active-Job claims.

## Backup and rollback

The pure library has no managed data root. Optional runtime migration is forward-only. Before
upgrade, stop all writers and copy the complete data root, including SQLite/WAL/SHM and every
Artifact payload. Rollback means restoring the complete backup made for the target downgrade;
never run an older release against schema version 4 or restore only one side of the
database/Artifact pair.
