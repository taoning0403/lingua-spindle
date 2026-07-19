# Data model

SQLite migration `src/linguaspindle/migrations/0001_initial.sql` implements the v0.1.0 relational
model through SQLAlchemy classes in `models.py`.

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

`sources` stores original name, validated kind, media type, size, checksum, import time, and the
Artifact containing the copied bytes. Source-to-Artifact deletion is restricted so a live Source
cannot point to removed metadata. A workflow never updates the original payload; re-import would
create a new Source/Artifact.

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

Kinds used by v0.1.0 include source, encoding, extracted text, segments, translations, QA,
TXT/JSON exports, manga manifests/pages, Adapter raw output, and CBZ export.

## TranslationProfile and ProviderConfig

`translation_profiles` stores name, language pair, Provider/model, style, context strategy, prompt
template/version, batch size, model-parameter JSON, and timestamps. Profiles are reusable
instance-level translation policy; the word “profile” has no person/account meaning. A Job embeds a
snapshot so later edits cannot alter history.

`provider_configs` stores only Provider ID, base URL, model, timeout, concurrency, retries, and
update time. It deliberately has no key/credential column. The runtime key remains only in process
Settings and is reported publicly as a configured boolean.

## TranslationSegment and QaFinding

`translation_segments` is unique by Job and sequence. It stores Project/Job, source and optional
translated text, status, model, Profile snapshot, prompt version, normalized error, and timestamps.
This lets retry skip successful segments and target failed ones without disturbing order. API/GUI
queries default to the most recently created Job with segments; an explicit Job ID accesses
history.

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
- Never store the runtime Provider key or a secret-shaped configuration field.
