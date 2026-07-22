# LinguaSpindle v0.3.1 product contract

This document defines the user-approved v0.3.1 target. It is not a progress report:
`PROJECT_STATE.md` records current implementation, ADRs record durable decisions, and
`acceptance/` records commands and results. v0.1.0 and v0.2.0 evidence remains historical and is
never rewritten by this milestone. v0.3.1 retains the v0.3.0 headless/core contract and adds
service-call hardening above the pure core.

## Identity and position

- Product: **LinguaSpindle**
- Repository/package/CLI: `lingua-spindle`, `linguaspindle`, `linguaspindle`
- Position: a headless, embeddable, caller-independent translation orchestration engine for
  novels and manga.

v0.3.0 removes the product GUI and calling-application business concerns. It does not reduce the
translation formats that reached v0.2.0 acceptance.

## Permanent boundaries

1. **No user system.** Never add registration, login, account, administrator, role, permission,
   organization, tenant, membership, owner, creator, quota, or collaboration concepts, fields, or
   routes. Optional perimeter identity stays outside LinguaSpindle.
2. **Standalone operation.** LinguaSpindle does not depend on `novel-platform`, its database,
   domain objects, or identity. A future consumer uses a versioned public Python or HTTP contract.
3. **Immutable sources.** Rebuild from the original source and write to an explicit new caller
   output. Never overwrite imported source bytes.
4. **Shared implementation.** High- and low-level Python APIs, optional CLI, optional HTTP, and
   optional runtime reuse the same pure processing/orchestration implementation. Interfaces do
   not implement Pipelines or invoke external tools directly.
5. **Loopback-default HTTP.** Anyone with network access can operate the optional instance. Remote
   access requires an explicit reverse proxy, private network, Tailscale, Cloudflare Access, VPN,
   or equivalent outer perimeter.
6. **Capability-driven integrations.** Select Adapters by declared capability/configuration, not
   product-name conditionals. Keep third-party tools, models, fonts, and GPU runtimes outside the
   core repository and record their licenses.
7. **Runtime-only secrets.** A caller injects Provider keys at the moment of use. Keys never enter
   serialized models, database views, events, errors, logs, Artifacts, fixtures, or output.

## v0.3.1 outcome

The default package is a side-effect-free Python library that can inspect, translate, and rebuild:

- TXT novels;
- common valid, unencrypted EPUB 2 and EPUB 3 novels;
- CBZ/ZIP manga; and
- individual PNG, JPEG, or WebP manga images.

It includes a deterministic offline Mock Provider and Mock Manga Adapter. It supports stable
segments/pages, caller-selected novel translation, caller-supplied/manual text, retry, events,
cooperative cancellation, partial results, stable errors, and versioned JSON-compatible results.

Optional layers provide the OpenAI-compatible Provider, the existing `manga-image-translator`
HTTP Adapter, SQLite/Artifact/Job recovery, CLI, and headless HTTP server.

v0.3.1 adds durable service idempotency, database-safe active Job coalescing, and request
correlation to the optional HTTP/runtime layers. It does not move HTTP, SQLite, identity, or
idempotency concerns into the pure core.

`import linguaspindle` must not read environment variables, create directories, open SQLite, or
start a thread. The pure core must not import FastAPI, Uvicorn, Typer, SQLAlchemy, or Playwright.

## Dependency direction

```text
optional CLI / headless HTTP
              |
optional local runtime (SQLite / Job / Artifact / recovery)
              |
pure synchronous orchestration core
         /                         \
TXT / EPUB / Provider        image / CBZ / Manga Adapter
```

Interfaces may call the public core directly. The optional runtime maps core DTOs to persistent
records and Artifacts; SQLAlchemy models are never public core types. Core objects accept only
explicit operation options and limits, not global runtime `Settings`.

## Public Python contract

Novel operations must include:

```text
inspect_document
extract_segments
translate_segments
rebuild_document
translate_document
```

Manga operations must include:

```text
inspect_manga
translate_manga
build_manga_output
```

The stable typed surface includes at least:

```text
DocumentManifest, Segment, SegmentLocator
MangaManifest, MangaPage
TranslationProvider, TranslationRequest, TranslationRecord, TranslationBatchResult
MangaTranslationAdapter, MangaTranslationResult
TranslationOptions, TranslationEvent, CancellationToken, BuildResult
LinguaError, ErrorCode
```

Public APIs accept path-like values and binary streams; bytes are a convenience for bounded
inputs. Every output path or stream is supplied by the caller. Persistent result types have a
schema version and JSON-compatible serialization/recovery. Long-term contracts use dataclasses,
Enums, Protocols, and bounded typed structures rather than open-ended database/service mappings.

## Novel selection and caller editing

Each Segment records:

- stable `segment_id` and deterministic order;
- source format/document and original text;
- content role;
- TXT source span or EPUB XML-slot locator;
- source hash and translation-input hash; and
- join/reconstruction information.

For an unchanged source and the same inspection policy, Segment IDs and order are stable.

- `selected_segment_ids=None` selects all Segments.
- An explicitly empty selection selects none and must never become “translate all.”
- Unknown IDs fail with a stable error before a Provider call.
- Unselected Segments are not overwritten.
- Existing successful or human-authored translations win and are not sent to the Provider.
- A caller can rebuild with a Segment-to-text mapping without any Provider.
- Concurrent completion cannot change output order.
- Partial failure preserves successes and a per-Segment normalized error.
- A caller can serialize results and later retry only failed or selected Segments.

LinguaSpindle does not add proofread/review/published business states, an editor, approval history,
or a translation-memory/CAT product.

## TXT contract

- Report encoding, confidence, newline style, and segmentation-rule version.
- Preserve paragraph, dialogue, and reasonable sentence boundaries within a configurable maximum
  Segment length.
- Trace every Segment to deterministic source offsets and preserve between-Segment source text.
- Rebuild by source spans rather than naïvely joining translated strings.
- Default output is UTF-8 with LF newlines and is recorded in `BuildResult`.
- Reject empty, binary-disguised, unrecognized-encoding, and over-limit input with stable errors.

## EPUB contract

Reuse and preserve the v0.2.0 structure-preserving EPUB path:

- validate first `mimetype`, container, OPF, EPUB 2/3 version, manifest, spine, navigation,
  cover/resources, parseable XML/XHTML, and internal references;
- reject encryption/protection, unsafe/ambiguous paths, symlinks, unsupported compression, and
  configured archive count/size/ratio/depth excess;
- extract ordered visible text through stable document/XML-slot locators;
- translate documented metadata, navigation, Ruby base, footnote, and image-alt/title slots while
  excluding tags, scripts, styles, code, SVG, Ruby pronunciation/fallback, URLs, paths, IDs,
  anchors, and binary resources;
- rebuild from the immutable source; retain original text for unmapped/failed slots;
- update target-language metadata while retaining reading order, navigation, links, cover, and
  non-text resources;
- reopen/reinspect output, validate package/reference invariants, and byte-compare members not
  intentionally modified; and
- publish only to an explicit different output path/stream.

`ArchiveLimits` is passed explicitly to the core. External `epubcheck` remains an optional
acceptance tool, not a default dependency. DRM bypass, dynamic browser rendering, and broad repair
of invalid publisher content remain out of scope.

## Manga contract

Retain `manga_full_v1`, single-image and CBZ/ZIP input, natural page order, translated image
output, raw Adapter result/log data, partial pages, normalized errors, and page-boundary
cancellation.

`MangaTranslationAdapter` is distinct from `TranslationProvider`. Its manifest declares Adapter
and upstream versions, invocation type, capabilities, formats, languages, GPU requirement,
health, cancellation/progress support, configuration help, upstream URL/license, and modification
status.

The default Mock Manga Adapter is deterministic and offline. The real
`manga-image-translator` HTTP Adapter remains optional and process-separated under ADR 0006:

- do not vendor/import/install/download its GPL source;
- do not package its models, fonts, containers, or GPU runtime;
- the operator installs, licenses, runs, and secures the service;
- default tests use the Mock or a fake HTTP service; and
- never describe either as real model execution.

The current real Adapter does not provide streaming internal progress or immediate mid-image
cancellation. Do not fabricate these capabilities. v0.3.0 adds no bubble/region editing protocol.

## Orchestration semantics

Use one simple synchronous orchestration implementation. The embedding caller chooses whether to
run it in a thread, task queue, or server.

The core owns deterministic ordering, bounded concurrency, bounded retry/backoff, retryable versus
terminal errors, attempt/usage reporting, progress events, cooperative cancellation, partial
success, and sensitive-value redaction. Novel translation invokes a text Provider; manga invokes
an image Adapter. These protocols share lifecycle semantics, not ambiguous call parameters.

## Optional dependencies

```text
pip install linguaspindle             pure core + mocks + TXT/EPUB
pip install linguaspindle[openai]     OpenAI-compatible HTTP Provider
pip install linguaspindle[manga]      real manga HTTP Adapter
pip install linguaspindle[runtime]    SQLite + Artifact store + persistent Jobs
pip install linguaspindle[cli]        headless CLI
pip install linguaspindle[server]     FastAPI/Uvicorn JSON server + runtime
pip install linguaspindle[all]        all supported optional layers
```

The default dependency graph must not contain FastAPI, Uvicorn, Typer, SQLAlchemy, Playwright,
browser binaries, or heavyweight manga components. Missing optional features return an actionable
extra-install message.

## Optional local runtime

- Retain instance-scoped Project, Source, Job, Step, Segment, QA, and Artifact records.
- Retain ordered durable Steps, progress, logs, pause/resume/cancel/retry, partial success,
  conditional Job claims, restart classification, and output recovery.
- Make the runtime a thin mapper over public core processing rather than a second TXT/EPUB/manga
  implementation.
- Constructing `LocalRuntime` may open configured persistence but never starts `JobRunner`.
- Migration 0003 adds a nullable stable Segment key/index and preserves all v0.2.0 novel and manga
  records and payloads. Upgrades are forward-only; rollback restores a complete stopped backup.

This remains a one-host SQLite/local-Artifact runtime, not a broker, object store, distributed
worker, or generic DAG editor.

## Optional CLI

The CLI is a thin adapter. It supports version reporting, TXT/EPUB inspection and Mock
translation, manga inspection and Mock translation, generated-output validation, Provider/Adapter
diagnostics, and—when runtime dependencies are installed—Project, Job, Artifact, export, and
server operations. It must not import optional runtime/server modules until a matching command is
used.

## Optional HTTP server

The FastAPI service is JSON/OpenAPI-only. It serves no reader, GUI, static JavaScript/CSS, or SPA
fallback. It retains health/capability status, Provider/Adapter diagnostics, Project/source/Job
lifecycle, controls, persistent segments, Artifact metadata/download, and exports. Novel callers
must be able to fetch Segments, request selected translation, and rebuild using an external
translation mapping. Manga retains CBZ/image upload, asynchronous Job status, and output download.

Long-running work uses the optional runtime. The API never reaches into SQLAlchemy tables or core
private helpers. It keeps typed OpenAPI and stable error envelopes and adds no auth/user model.

## Service-call idempotency and request correlation

The following operations accept `Idempotency-Key`: create Project, create Profile, create Job,
translate an explicit Segment selection, rebuild, and retry Job. The key is 8–128 safe ASCII
characters and is SHA-256 hashed immediately; only the hash, operation scope, versioned semantic
fingerprint, status, safe resource reference, error metadata, and request ID may be persisted.
Raw keys, Provider keys, uploaded content, and caller translation text never enter idempotency
records or managed logs.

Default compatibility mode accepts a missing key. Required mode is explicitly enabled with
`LINGUASPINDLE_REQUIRE_IDEMPOTENCY_KEY=true` and returns 428 when a covered call lacks one. Same
key/same semantics replays the retained resource; changed semantics conflict; concurrent work is
in progress; and interrupted synchronous external work becomes indeterminate. Stable errors and
HTTP 409 distinguish those states. Completed replay returns 200 and replay metadata without
duplicating a Provider call or persistent resource.

Equivalent active Jobs coalesce by a versioned execution fingerprint containing immutable source,
Pipeline/version, effective Profile, Provider/model non-secret configuration, Adapter
configuration, and language pair. A SQLite partial unique index protects queued, running, paused,
and cancelling states across processes. Terminal state permits a deliberate rerun with a new key.
Project upload publication and its claim are atomic; concurrent loser staging is removed.

Every HTTP success/error includes `X-Request-ID`. A safe caller ID is retained or a UUID is
generated. The first Job request ID is persisted and copied into Step log details. Pause, resume,
and cancel preserve their natural state-machine idempotency and need no durable key record.

## GUI and caller responsibility

v0.3.0 removes `src/linguaspindle/web/`, static package data, root/app/style GUI routes, SPA
fallback, GUI-specific text, Playwright/browser dependencies, Node/browser checks, screenshots,
and browser traces. It does not replace them with another frontend.

The embedding caller owns readers, proofreading UI, local-retranslation controls, revision and
approval history, bookshelf/project/content management, and business state.

## Security, storage, and licensing

- Archive and source limits are explicit core options and optional runtime environment settings.
- Imported runtime Sources remain immutable Artifacts; runtime-managed payload paths stay private.
- Base URLs reject embedded credentials, query strings, and fragments.
- Mock tests require no key, paid service, external network, model, or GPU.
- LinguaSpindle core remains Apache-2.0; dependencies and external services keep their own terms.
- Keep `third-party-components.toml` and `THIRD_PARTY_NOTICES.md` current, including code, models,
  fonts, integration method, modifications, and redistribution status.

## v0.3.1 acceptance

Required evidence includes:

1. import-side-effect and dependency-boundary tests with core-only installation;
2. caller-defined Provider and Manga Adapter tests with no global Settings;
3. versioned result serialization/recovery and credential-leak tests;
4. TXT/EPUB stable Segment IDs, empty/selected/unknown selection, human mapping, deterministic
   order, partial failure, source mismatch, structure preservation, malicious input, and immutable
   output tests;
5. single-image/CBZ Mock flow, page order, archive guards, fake real-Adapter protocol mapping,
   timeout/invalid-response normalization, partial pages, and page-boundary cancellation tests;
6. v0.2.0 novel/manga data migration and Artifact compatibility;
7. isolated Wheel/install/`pip check` checks for core, openai, manga, runtime, cli, server, and all;
8. proof that the Wheel/image contains no Web resources, browser dependency, upstream manga
   source, model, or font;
9. Ruff, strict mypy, compileall, pytest, branch coverage, Python 3.11–3.14 CI, and practical
   Windows core coverage; and
10. durable same-key replay/conflict/restart tests and two-instance SQLite concurrency tests for
    Project upload, active Job coalescing, orphan cleanup, terminal reruns, and Provider call count;
11. compatibility/required modes, natural controls, request-ID persistence, OpenAPI headers, and
    Provider-Key/Idempotency-Key leak scans;
12. Compose parsing and a hardened non-root/read-only/Volume Docker health run with required mode;
    and
13. a checksummed `acceptance/v0.3.1/` archive containing reports, exact Wheel, deterministic
    TXT/EPUB/manga samples, environment, command log, migration/extras/container/security
    evidence, and checksums.

Report Pass, Fail, Blocked, Not executed, and Optional external test distinctly. A Mock/fake is not
evidence of a paid Provider or real manga model. Real paid Provider, real external manga model,
external `epubcheck`, and unavailable platforms remain explicit optional external tests.

## Explicit exclusions

No GUI, reader, proofreader, approval/revision workflow, user system, caller bookshelf/content
management, professional CAT editor, general translation memory, plugin marketplace, arbitrary
network code installation, distributed scheduling, DAG editor, PDF, DOCX, MOBI, AZW3, DRM bypass,
novel/manga downloader, resource-site scraping, Photoshop-class editor, OCR training, mobile
client, formal `novel-platform` coupling, PostgreSQL, Redis, Kafka, S3, or Kubernetes is introduced.

## Version and publication control

The release candidate declares package/image version `0.3.1`; it is not a published release until
every mandatory acceptance item passes and the v0.3.1 archive/checksums are complete. Development
must not move/recreate the v0.3.0 tag, rewrite historical acceptance, push a remote branch/tag,
create a GitHub Release, publish Wheel/image artifacts, or deploy a server. Publication and
deployment require separate authorization after report review.
