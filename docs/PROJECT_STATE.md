# Project state

Last reviewed against the v0.2.0 development contract, working implementation, and publication
baseline on 2026-07-21. The active milestone is v0.2.0. Its package version is `0.2.0`, and the
evidence baseline `6c6f99590950f460c3d32f38437f56c39492177f` is on remote `main`. The annotated
`v0.2.0` tag and GitHub prerelease remain pending the separately authorized publication step.

## Current milestone outcome

LinguaSpindle v0.2.0 extends the persistent, restart-aware translation orchestration engine with a
structure-preserving EPUB 2/3 path and bounded large-file transfer. TXT novel and CBZ/image manga
remain on their existing Pipelines. One `ApplicationService` and sequential `JobRunner` are shared
by the no-login Web GUI, Typer CLI, and FastAPI asynchronous Job API.

The product remains a single-instance standalone tool. It has no account, identity, tenant,
permission, ownership, quota, or collaboration model; no `novel-platform` dependency; loopback-
default networking; immutable imported Sources; runtime-only Provider secrets; SQLite metadata;
and one local Artifact store.

## Implemented v0.2.0 surface

- Common valid, unencrypted EPUB 2/3 import with first-mimetype, container, OPF, manifest, spine,
  navigation, XML/XHTML, internal-reference, cover, and package metadata inspection.
- Explicit visible-text policy for XHTML body/navigation text, NCX labels, image alternative/title
  text, Ruby base text, and selected OPF metadata. Scripts, styles, code, SVG, Ruby pronunciation,
  URLs, paths, anchors, IDs, CSS, JavaScript, and binary resources are excluded.
- Deterministic source-document/XML-slot locators, at-most-1,800-character text parts, exact
  inter-part joiners, source/input hashes, and persisted Segment lineage in migration 0002.
- `novel_epub_v1` Pipeline: inspect → segment → existing Provider translation → existing QA →
  rebuild/validate EPUB. Source kind chooses the compatible TXT/EPUB/manga Preset.
- Conservative cross-Job Segment reuse when immutable input location/content and the complete
  effective non-secret translation policy match.
- Reconstruction from the immutable source archive with source-text fallback for failed/missing
  translations, preserved reading order/navigation/references/resources, BCP 47 OPF/XHTML target
  language, and a new traceable EPUB Artifact.
- Independent output reopen/re-inspection, package/reference validation, re-import, and byte-for-
  byte comparison of archive members not intentionally modified.
- Streamed/bounded source publication, an outer multipart request-size guard, file-based HTTP
  downloads, and atomic streamed CLI Artifact copies.
- Central configuration for upload bytes, ZIP member count, total/per-member expansion,
  compression ratio, and path depth; unsafe/protected/malformed/unsupported EPUBs receive stable
  normalized errors before a usable Project is published.
- Bounded raw/expanded runtime-key scans plus content-safe exact-key replacement preserve ordinary
  user prose containing words such as `password` or `secret`; diagnostic/configuration redaction
  remains strict.
- Typed OpenAPI Project/Job/Artifact responses and stable 400/404/409/413/422 error envelopes;
  active Jobs must be cancelled to a terminal state before their Project can be deleted.
- Forward-only atomic schema migration that retains existing v0.1.0 Project, Source, Job, Step,
  Segment, QA, and Artifact rows.

Exact EPUB rules and limitations are in `docs/epub.md`; module and verification routing is in
`docs/MODULE_MAP.md`.

## Retained v0.1.0 capabilities

- Durable ordered Job/Step state, weighted progress, logs, normalized errors, partial success,
  cooperative pause/resume/cancel, failed-work retry, conditional Job claim, and restart recovery.
- TXT encoding detection, paragraph/dialogue-preserving segmentation, persisted translation rows,
  basic QA, and TXT/JSON export.
- Deterministic offline Mock Provider and real opt-in OpenAI-compatible Chat Completions Provider
  with runtime-only key, concurrency/timeout/retry limits, normalized errors, and redaction.
- CBZ/ZIP or single-image manga path, Mock Manga flow, and protocol-only HTTP Adapter for a
  separately operated `zyddnys/manga-image-translator`; no upstream code/model/font distribution.
- Polling Web dashboard and Project/Job/result/Artifact surfaces; CLI commands and stable exit
  envelopes; asynchronous API and OpenAPI; doctor diagnostics; loopback Compose; and non-root,
  read-only-root core container deployment.

## Verification state

The final v0.1.0 evidence remains immutable and indexed at `acceptance/v0.1.0/README.md`, including
its later Docker/WSL supplement and the limits of native Windows, real manga-model, and real paid-
Provider execution.

The v0.2.0 source candidate `f662c4844bd7990b3197f39314841b9c903deae1` has completed the
required local acceptance matrix with final status **Pass / release pending**. Evidence belongs
only under `acceptance/v0.2.0/`; the human-readable conclusion is in
`acceptance/v0.2.0/reports/acceptance-report.md`. The later evidence-only commit
`6c6f99590950f460c3d32f38437f56c39492177f` is now on remote `main` and contains no runtime-source
change from that candidate. The acceptance report's statement that no push had occurred records
its historical execution point and remains unchanged. No v0.2.0 tag or GitHub Release exists.

Final executable evidence includes 149 passing tests with 3 explicit default skips and 83% total
branch-aware coverage; a real Chromium rerun with 2 browser tests passing and only the paid
Provider test skipped; deterministic Mock EPUB/TXT/manga artifacts; installed-Wheel Web and
migration-resource smoke checks; and an isolated Linux/arm64 Docker Compose run proving health,
loopback publication, non-root/read-only execution, HTTP Artifact integrity, and restart
persistence. Native Windows/WSL, a real paid Provider, a real manga model, and external
`epubcheck` remain accurately marked as optional external tests not executed in this run.

Release preparation on 2026-07-21 added `.github/workflows/ci.yml` without changing `src/`,
migrations, dependencies, Docker runtime configuration, or product behavior. Local default suites
on Python 3.11.13, 3.12.11, 3.13.7, and stable 3.14.6 each completed with 149 passing tests and the
same 3 explicit skips. The Python 3.12 coverage rerun remained 149 passed, 3 skipped, and 83%.
The browser command first failed only because the sandbox denied `127.0.0.1` binding; the same
command in an approved loopback environment completed with 2 passed and 1 paid-Provider skip. A
fresh isolated Linux/arm64 Compose image and project repeated health, non-root/read-only/loopback
security, empty-key Mock Job, download integrity, restart persistence, and test-only Volume
cleanup. Hosted GitHub Actions remain pending until the exact release-preparation commit is
separately authorized for remote `main`.

Required v0.2.0 gates include EPUB unit/integration/interface/browser coverage, malicious and
resource-limit fixtures, export re-import/resource equality, controls/recovery/reuse, TXT/manga
regression, whole-data-root secret scanning, installed-wheel resources, and Docker persistence.
Real paid Provider and external EPUB validator/model tests remain explicit opt-ins.

## Upgrade and deployment state

- v0.1.0 data is migrated in place by package migration `0002_epub.sql`; users are not asked to
  delete the old data root.
- Back up the entire stopped data root before upgrade. Rollback is by restoring that complete
  pre-upgrade backup and running v0.1.0, not by downgrading schema 0002 in place.
- Docker Compose continues to publish only `127.0.0.1:8765`, runs UID/GID 10001 with a read-only
  root, and persists `/data`. Its bounded `/tmp` is 128 MiB to accommodate the default 100 MiB
  multipart upload spool; raising upload limits requires matching temporary-storage/proxy limits.
- The core image still contains no external manga stack, model, font, GPU runtime, browser, paid
  key, or external EPUB validator.

## Known limitations and deliberate omissions

- One host and data root remain the concurrency/deployment boundary; there is no broker,
  distributed worker, PostgreSQL, object store, or multi-host scheduling.
- EPUB support targets common valid, unencrypted EPUB 2/3. DRM bypass, protected content, broad
  invalid-publisher repair, dynamic JavaScript-rendered text, PDF, DOCX, MOBI, and AZW3 are out of
  scope.
- Modified XML documents may be serialized with different namespace prefixes, declarations,
  attribute order, or insignificant formatting. Validated semantics/references are retained;
  unmodified member payloads are byte-compared.
- Built-in validation is structural and reference-oriented; reader-specific layout behavior can
  still depend on publisher CSS/fonts and the target reader. External `epubcheck` is optional.
- The GUI provides progress, basic results/QA, controls, and downloads, not a professional
  sentence editor, CAT workflow, translation memory, or collaboration system.
- Process exit still fails the active Step as `PROCESS_INTERRUPTED`; retry resumes from durable
  Step/Segment boundaries, not in the middle of a Provider/Adapter call.
- Manga Adapter streaming progress and immediate mid-image cancellation are unchanged from
  v0.1.0. The heavyweight upstream remains operator-managed.
- Remote access still requires an explicit private network or access proxy. Its identity must not
  become an application user model.

## Decisions

ADRs 0001–0006 retain the no-user, standalone, shared-core, Artifact, stack, secret, and manga
Adapter boundaries. ADR 0007 owns structure-preserving EPUB reconstruction, deterministic Segment
reuse, streamed payload transfer, and bounded archive processing. Reverse an accepted decision
only with a new superseding ADR.

## Update triggers

Update this file when capability, verification, deployment evidence, limitation, or milestone
state changes. Put exact product requirements in `PRODUCT_SPEC.md`, durable rationale in ADRs,
navigation in `MODULE_MAP.md`, and versioned command transcripts under `acceptance/`.
