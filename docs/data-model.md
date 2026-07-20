# Data model

SQLite migrations `src/linguaspindle/migrations/0001_initial.sql` and `0002_epub.sql` implement the
v0.2.0 relational model through SQLAlchemy classes in `models.py`. Migration 0002 extends existing
v0.1.0 rows in place; it does not replace the database or require a new data root.

```text
LinguaSpindle instance
├── Project 1 ── * Source ── 1 immutable source Artifact
├── Project 1 ── * Job 1 ── * StepRun 1 ── * StepLog
│                         ├── JSON input/output Artifact IDs
│                         ├── * TranslationSegment
│                         └── * QaFinding
├── Project 1 ── * Artifact (optional Job/Step provenance)
├── TranslationProfile (instance-scoped, secret-free)
└── ProviderConfig (instance-scoped, secret-free)
```

There is no User, Account, Session, Role, Permission, Organization, Tenant, Membership, owner,
creator, or identity foreign key. All records belong directly to the one instance.

## Representation choices

- Domain IDs are UUID4 strings; StepLog and QaFinding use local integer sequence IDs.
- Timestamps are UTC datetimes serialized as ISO 8601.
- Status and error vocabularies are strings validated by explicit state machines in
  `orchestration/state.py`.
- Flexible metadata/configuration and Artifact link lists use JSON text; secrets are sanitized
  before serialization.
- Large and immutable payload bytes do not enter SQLite.
- Forward-only migration versions are recorded in `schema_migrations`.

SQLite enables foreign keys, WAL, and a five-second busy timeout for each connection.

## Project and Source

`projects` stores name, kind (`novel`/`manga`), language pair, and timestamps. A Project directly
owns Sources, Jobs, and Artifacts. Deletion cascades relational children only after application
confirmation, then bounded storage cleanup removes its payload subtree.

`sources` stores original name, validated kind (`txt`, `epub`, `cbz`, or `image`), media type, size,
checksum, import time, compact inspection metadata, and the Artifact containing the copied bytes.
EPUB inspection metadata includes version, title/creator/language values, cover/navigation display
data, and chapter/document/resource/text-unit counts; the full structural manifest is a generated
Artifact. Source-to-Artifact deletion is restricted so a live Source cannot point to removed
metadata. A workflow never updates the original payload; re-import creates a new Source/Artifact.

## Job and StepRun

`jobs` stores Project, optional TranslationProfile, Pipeline key/version, Provider/Adapter IDs,
status, weighted progress, cooperative control request, secret-free Profile snapshot, request/
start/end/update times, claim token, and normalized terminal error.

Required Job states are:

```text
queued -> running -> succeeded | partially_succeeded | failed
   |          |  \-> cancelling -> cancelled
   |          \----> paused -> queued
   \---------------------------> paused | cancelled
failed | partially_succeeded -> queued (explicit retry)
```

Terminal success/cancellation does not resume. Retry is limited to failed/partial Jobs.

`step_runs` has one row per stable Pipeline Step key and Job. It stores order, capability,
executor type/ID, status, attempt count, timestamps, progress, input/output Artifact ID arrays,
secret-free configuration snapshot, and normalized error. `step_logs` is append-only across
retries. Before reset, retry appends the previous status/error/timestamps, so prior failure evidence
and the monotonic attempt count remain auditable without a separate StepAttempt table.

Successful upstream Step rows keep their output IDs on retry/restart. Downstream rows are reset
only from the earliest failed/partial order.

## Artifact

`artifacts` records UUID, required Project, optional Job/Step provenance, kind, safe filename,
media type, byte size, SHA-256, unique private relative storage key, redacted metadata JSON, and
creation time.

Step input/output relationships are ordered Artifact-ID arrays on the StepRun. Additional lineage
is represented in Artifact metadata such as `source_artifact_id` or
`source_page_artifact_id`. Public interfaces return Artifact IDs and download URLs, never storage
keys or caller-controlled absolute paths.

Payload publication precedes row commit and is atomic within the destination directory. If row
commit fails, the new payload is removed. Reads check the stored byte size; checksums are exposed
for independent integrity verification.

Kinds used by v0.2.0 include source, encoding, extracted text, TXT/EPUB segments and translations,
QA, EPUB package/validation reports, TXT/JSON/EPUB exports, manga manifests/pages, Adapter raw
output, and CBZ export.

## TranslationProfile and ProviderConfig

`translation_profiles` stores name, language pair, Provider/model, style, context strategy, prompt
template/version, batch size, model-parameter JSON, and timestamps. Profiles are reusable
instance-level translation policy; the word “profile” has no person/account meaning. A Job embeds a
snapshot so later edits cannot alter history.

`provider_configs` stores only Provider ID, base URL, model, timeout, concurrency, retries, and
update time. It deliberately has no key/credential column. The runtime key remains only in process
Settings and is reported publicly as a configured boolean.

## TranslationSegment and QaFinding

`translation_segments` is unique by Job and sequence. Every row stores Project/Job, source and
optional translated text, status, model, Profile snapshot, prompt version, normalized error, and
timestamps. EPUB rows additionally store source Artifact, source document, content role, a JSON
XML-slot locator, source-text hash, full translation-input hash, and optional reused Segment ID.
The self-reference uses `SET NULL`; historical reuse remains informative without preventing
Project/Job deletion.

The input hash is conservative: source archive/content/location plus effective non-secret
language, Provider/model, style, prompt, model parameters, and context policy must match before a
successful earlier Segment in the same Project is reused. TXT retains its existing per-Job
behavior. Indexes on Project/input-hash/status and Job/document/sequence support reuse lookup and
ordered chapter/document inspection.

These fields let retry skip successful Segments, target failed ones without disturbing order, and
reconstruct an EPUB slot deterministically. API/GUI queries default to the most recently created
Job with Segments; an explicit Job ID accesses history.

`qa_findings` references Project, Job, and optional segment with category, severity, message, and
time. Deleting/replacing a Job's segments also removes their findings. v0.1.0 QA is diagnostic and
read-only, not an editorial revision model.

## Recovery and invariants

- Persist state before reporting it through an interface.
- Claim a queued Job with a conditional SQLite update.
- Never repeat succeeded Steps unconditionally after restart.
- Mark an interrupted active Step/Job `PROCESS_INTERRUPTED`; preserve retry evidence.
- Remain `cancelling` until an active safe boundary is reached.
- Keep source bytes immutable and Artifact keys under the configured root.
- Never publish a successful Artifact row for a missing/partial payload.
- Never treat a staged upload or temporary EPUB export as a Project/Artifact after validation
  failure; remove the temporary payload.
- Reuse an EPUB translation only when its complete translation-input hash matches.
- Rebuild EPUB from the immutable source and publish the output as a different Artifact.
- Reject Project deletion while a related Job is non-terminal; terminal cancellation precedes
  deletion.
- Never store the runtime Provider key or a secret-shaped configuration field.

## Forward migration, backup, and rollback

Schema migrations and their `schema_migrations` marker are committed atomically. On first v0.2.0
startup, `0002_epub.sql` adds nullable/defaulted Source and Segment fields plus indexes, so v0.1.0
TXT/manga records remain readable with empty/default EPUB metadata.

Before upgrading, stop writes and back up the entire data root, including SQLite, WAL/SHM when
present, and Artifact payloads. Application migrations are forward-only: rollback means stop
v0.2.0, restore the complete pre-upgrade data-root backup, then run v0.1.0. Do not run v0.1.0
against a database already migrated to schema 0002, and do not restore only SQLite or only the
Artifact directory.
