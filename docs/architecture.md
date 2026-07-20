# Architecture

LinguaSpindle v0.2.0 is a local-first Python modular monolith with process-separated external
capabilities. Windows, Linux, server, Docker, Web, CLI, and API use one business implementation.

```text
Static Web GUI       Typer CLI       FastAPI / OpenAPI
       \                |                 /
        +-------- interface adapters ----+
                         |
                ApplicationService
                         |
          durable sequential JobRunner
             /             |             \
    Translation Providers  |       capability Adapters
                            |               |
                     Artifact API     external HTTP service
                       /       \
               SQLite metadata  local immutable payloads
```

ADRs 0001–0007 own the durable boundaries. The implementation is intentionally one-host and does
not introduce a broker, distributed worker, external database, frontend build service, or
application identity layer.

## Concrete stack

- Python 3.11+ packaged with setuptools.
- FastAPI 0.115/Uvicorn for HTTP, multipart input, static GUI, and OpenAPI.
- Typer for CLI commands.
- SQLAlchemy 2 over SQLite WAL; package-owned forward-only SQL migrations.
- Atomic local Artifact payload store under one configurable data root.
- Durable in-process polling worker with a SQLite compare-and-update claim.
- HTTPX for OpenAI-compatible and manga HTTP integrations.
- Server-served HTML/CSS/ES-module GUI; polling is the only progress transport.
- pytest, Ruff, mypy, coverage, and opt-in Playwright Chromium acceptance.

ADR 0004 records why this stack fits a single-instance deployment. EPUB inspection/reconstruction
uses the Python standard library ZIP/XML implementation plus the existing storage and Job
boundaries; it does not add an EPUB service or external runtime dependency.

## Interface and application boundary

`interfaces/api.py`, `interfaces/cli.py`, and `web/app.js` adapt requests and responses only.
They call `ApplicationService`; neither interface defines Pipelines, calls Providers/Adapters, or
writes Artifact storage directly. CLI and API integration tests create data through one surface
and observe it through the other.

The FastAPI lifespan constructs one `ApplicationService` and one `JobRunner`. Creating an HTTP Job
returns `202` immediately; the runner claims it from SQLite. CLI `run` creates the same Job and may
drive the same runner synchronously. The GUI polls persisted Job detail.

Multipart source bodies are bounded before parsing, then copied from `UploadFile` into the managed
Artifact store as a stream. The application layer independently enforces the exact source-byte
limit. HTTP downloads use a verified private Artifact path with a file response, and CLI output
uses an atomic streamed copy. Interfaces never expose storage keys or read the whole payload merely
to transfer it.

The GUI opens directly to the dashboard. There are no login/account/profile pages, auth
dependencies, permission filters, or identity-shaped routes. Translation Profiles are
instance-scoped translation policy, not personal profiles.

## Orchestration and recovery

Pipelines are versioned ordered code definitions in `orchestration/pipelines.py`:

- `novel_txt_v1`: encoding → extraction → segmentation → Provider translation → QA → TXT/JSON.
- `novel_epub_v1`: package inspection → located visible-text segmentation → Provider translation
  → QA → reconstructed and validated EPUB.
- `manga_full_v1`: safe import → `manga_full_pipeline` Adapter → CBZ.

Project kind and immutable Source kind select a compatible Preset. Novel remains the domain kind;
TXT and EPUB are Source formats, not competing Project or task models.

Each Job snapshots Pipeline version, Provider/Adapter ID, and a secret-free Translation Profile.
Each ordered Step persists state, attempt count, timestamps, progress, input/output Artifact IDs,
configuration, normalized error, and append-only logs.

The runner selects work by status and atomically changes one queued Job to running. It persists at
Step and segment/page boundaries. A Step passes only Artifact identities through orchestration;
`ExecutionContext` resolves payload bytes privately at the storage boundary.

Pause and cancellation are cooperative:

- queued pause is immediate; active pause remains requested until the next segment/page boundary;
- active cancel first becomes `cancelling` and becomes `cancelled` only at a safe boundary;
- pending downstream Steps are then marked cancelled; and
- the real manga HTTP Adapter declares no immediate cancellation, so the current image call is
  allowed to return or time out before cancellation completes.

Retry reopens the earliest failed/partial Step and downstream Steps. Successful upstream Steps and
successful translation segments are reused. Attempt counts and prior error evidence remain in
Step logs. A process restart classifies an active Step/Job as failed with `PROCESS_INTERRUPTED`;
the operator retries explicitly. Already completed Steps are never unconditionally rerun.

EPUB Segments add the source Artifact, source document, XML-slot locator, content role, source
hash, translation-input hash, and optional reused Segment lineage. Reuse across Jobs is allowed
only when the exact immutable location/content and effective non-secret translation policy match.

This is not a DAG editor or distributed scheduler.

## Persistence and Artifact boundary

All mutable state is below `LINGUASPINDLE_DATA_DIR`. SQLite holds metadata and small structured
records; payload bytes live under `artifacts/`. WAL, foreign keys, a busy timeout, and bounded
single-row Job claims support one local process/host boundary.

Imported Source bytes are copied once and never modified. Every source, extracted text, segments,
translation set, QA report, manga page, Adapter raw output, and export has a UUID Artifact,
checksum, size, media type, provenance, safe relative storage key, and metadata. Writes use a
same-directory temporary file, `fsync`, and atomic replacement before the database row is
published; a metadata failure removes the payload. Filenames and storage resolution prevent path
traversal. Archive member count, expanded size, and path are validated before extraction.

Project deletion requires explicit confirmation and is rejected while any queued, running,
paused, or cancelling Job exists; the operator must cancel it to a terminal state first. A
confirmed eligible deletion removes relational metadata and only the generated Project subtree
under the configured Artifact root. Backups must include the whole data root so metadata and
payloads remain consistent.

### EPUB package boundary

The EPUB inspector treats ZIP/XML as untrusted data. It validates the uncompressed first
`mimetype`, container/OPF, EPUB 2/3 version, manifest, spine, navigation, parseable XML/XHTML, and
internal resource references. It rejects encryption metadata, traversal/absolute/backslash paths,
symlinks, duplicate or portable-name-conflicting entries, unsafe compression, and configurable
member-count, total expansion, per-member expansion, compression-ratio, and path-depth excess.
Archive hashing, secret scanning, and resource verification use bounded reads. XML parsing,
reconstruction, and byte comparison may buffer at most one member whose announced and observed
size is already bounded by the per-member limit. Members are never extracted to
caller-controlled paths.

The inspection Artifact owns the structural manifest and ordered visible-text locators. Export
starts from the immutable source ZIP, modifies only located XML text slots plus OPF/XHTML language,
preserves failed/missing translations as source text, and keeps other payload bytes identical.
Before atomic publication it reopens and re-inspects the temporary EPUB, validates package and
reference invariants, and compares unchanged members. See ADR 0007 and `docs/epub.md`.

## Provider and secret boundary

The Mock Provider is a first-class deterministic implementation. The OpenAI-compatible Provider
uses Chat Completions with configured base URL/model, a process semaphore, timeout, bounded
exponential retry, and stable rate-limit/model/output errors.

ADR 0005 permits only runtime resolution from `LINGUASPINDLE_OPENAI_API_KEY`. ProviderConfig,
TranslationProfile, Job/Step snapshots, and public status contain no secret field. Base URLs reject
credentials/query strings. API requests forbid unknown secret fields. Before managed persistence,
known runtime values, bearer headers, key assignments, and secret-shaped mapping keys are
redacted in diagnostics and configuration payloads. User-authored book text and metadata use a
content-safe policy that removes only the exact active runtime key, so ordinary phrases such as
`password: castle` are not rewritten. Imported sources containing that key are rejected before
publication. Binary and ZIP-based output Artifacts are checked for the key in raw bytes and in
bounded expanded members. Tests scan databases/WAL, logs, Artifacts, exports, and compressed
members for the test key.
When a compatible endpoint returns standard prompt/completion/total token counts, only those
non-negative integers are retained in a redacted Step log for audit; raw Provider responses and
headers are not persisted.

This protects application-managed serialization, not arbitrary credentials unknown to the
process. Imported content and external data remain sensitive and should not be publicly shared.

## Adapter boundary

`AdapterManifest` declares identity, versions, invocation type, capability, formats, languages,
GPU/cancel/progress support, health/configuration, upstream/license, and modification status.
`AdapterRegistry` validates a requested capability. Application and orchestration code do not
branch on upstream product names.

v0.1.0 includes a built-in Mock Manga Adapter and a protocol-only
`MangaImageTranslatorHttpAdapter`. The real Adapter expects an operator-managed
`manga-image-translator` service, health-checks `/openapi.json`, and posts each image to
`/translate/with-form/image`. It validates image output and records translated plus redacted raw
Artifacts. Partial pages remain exportable.

No external source, model, font, container, or GPU dependency is in the core repository/image.
ADR 0006 and `third-party-components.toml` record the GPL process boundary and incomplete upstream
asset inventory.

## Trust, networking, and deployment

All durable state belongs directly to the instance. There is no User, Account, Session, Role,
Permission, Organization, Tenant, Membership, owner, or creator concept. Anyone with network
reachability has full instance capability.

Non-container startup binds to `127.0.0.1` by default. The container listens on its isolated
network interface, while supplied Compose publishes only to host `127.0.0.1`. Remote deployment
must add an outer private network/access proxy deliberately; its identity remains outside the
domain. See ADR 0001 and `docs/docker.md`.

The core image runs as UID/GID 10001, keeps external heavyweight tools out, uses a persistent
`/data` volume, and has a read-only root filesystem under Compose.

## Errors and observability

Stable codes cover configuration, upload/archive limits, unsafe archives, invalid/unsupported/
protected EPUB, export validation, Adapter unavailable, external command, timeout, invalid format,
model API, rate limit, task cancellation, missing output, not found, invalid state, process
interruption, storage, and unknown errors. API and CLI present readable normalized envelopes.
Step logs keep redacted details; raw Adapter metadata is a separate Artifact. Progress is derived
from persisted Step weights and real segment/page boundaries—unsupported external progress is not
invented.

## Deliberate v0.2.0 limits

- one host/data root and in-process worker;
- polling only;
- TXT and common unencrypted EPUB 2/3 novels plus CBZ/image manga;
- basic read-only result inspection, not a full editor;
- no transparent mid-call resume after process death;
- no streaming manga protocol/progress; and
- no built-in installation or redistribution of external tools/assets;
- no DRM bypass, dynamic browser rendering of book content, or broad publisher-format repair; and
- no PDF, DOCX, MOBI, or AZW3 support.
