# LinguaSpindle v0.3.1 acceptance report

> **Final status: Pass / release pending.** All mandatory local gates passed for clean source
> candidate `1d5949437bbbbd0bdbeb1a86d407832dd2d28c3c`. Optional external tests and remote CI are
> reported separately and are not represented by mocks or local substitutes.

- Report date: 2026-07-22 (Asia/Shanghai)
- Branch: `codex/v0.3.1-service-hardening`
- Source candidate: `1d5949437bbbbd0bdbeb1a86d407832dd2d28c3c`
- Host: macOS 26.5.2 / Darwin 25.5.0, arm64, Python 3.12.11
- Container: Docker 29.6.1, Linux/arm64
- Package version: `0.3.1`
- Test policy: deterministic offline Mock Provider and Mock Manga Adapter by default

The commit containing this archive adds retained evidence and the final maintained project-state
conclusion only. The source candidate above is the exact clean revision used for final static
checks, the test suite, Wheel build, isolated extras, and Docker image build.

## Conclusion

v0.3.1 completes the requested service-call hardening without changing the pure TXT/EPUB/manga
core boundary. The optional HTTP/runtime layers now provide durable operation-scoped idempotency,
database-enforced active Job coalescing, atomic Project publication, conservative interrupted-call
recovery, and request correlation. No user/account/tenant model, caller-domain coupling, GUI,
broker, PostgreSQL, Redis, or new external runtime dependency was introduced.

The six covered POST operations validate an 8–128 character `Idempotency-Key`, hash it immediately,
and store only its hash plus a versioned semantic fingerprint and safe resource/error metadata.
Same-key/same-request replay returns the retained resource, changed semantics conflict, live work
reports in-progress, and uncertain external effects become indeterminate. Equivalent active Jobs
coalesce through a partial SQLite unique index across two application instances. Terminal Jobs
release the slot for intentional reruns.

Every HTTP response includes a safe `X-Request-ID`. First Job correlation is retained on the Job
and Step logs. Compatibility mode remains the default; required mode returns 428 for a missing key.
The live container confirmed this mode and returned `IDEMPOTENCY_KEY_REQUIRED` with the supplied
request ID. Raw Idempotency-Keys and Provider keys were absent from persisted state, logs,
fingerprints, Artifacts, exports, the exact Wheel, and retained evidence.

The complete suite passed: **248 passed**, **0 skipped**, **84% branch-aware coverage**, above the
v0.3.0 baseline of 83%. Ruff formatting/lint, strict mypy, compileall, migration tests, Compose
parsing, and focused concurrency/security suites passed.

The exact Wheel passed seven isolated environments: core, openai, manga, runtime, cli, server,
and all. Every installation, `pip check`, dependency inventory, and offline smoke passed. The
Wheel contains migrations 0001–0004 and no GUI/browser resources.

The Linux/arm64 image is bound to the source candidate through its OCI revision label. It became
healthy as UID/GID 10001 with a read-only root, writable bounded `/tmp`, a named `/data` Volume,
`no-new-privileges`, and a host port published only on `127.0.0.1`. Root, health, system, forced
428/Request ID, and migration-0004 schema probes passed. The temporary container and Volume were
removed; their residual scan is empty. The local acceptance image is retained and unpublished.

## Required acceptance matrix

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| A01 | Preserve published v0.3.0 tag/archive | Pass | Historical checksums pass; tag remains `77974cbf47de2d40ac923e399c631056902b9f70`; no historical file changed. |
| A02 | Durable hashed-key idempotency and semantic fingerprints | Pass | Unit/integration tests cover validation, normalization, restart replay, conflict, in-progress, failed, and indeterminate states. |
| A03 | Concurrent Project upload safety | Pass | Same-service and two-instance races publish one Project/Source/Artifact and remove loser staging. |
| A04 | Database-enforced active Job coalescing | Pass | Same/different keys and two-instance races return one active Job; terminal reruns and Profile changes are covered. |
| A05 | Selected translation, rebuild, and retry replay | Pass | Persisted resource replay does not repeat Provider, rebuild, Artifact, or retry side effects. |
| A06 | Compatibility/required modes and natural controls | Pass | Default missing-key compatibility, forced 428, and repeated pause/resume/cancel all pass. |
| A07 | Request correlation | Pass | Generated/caller IDs occur on every success/error and persist on Job/Step evidence. |
| A08 | Stable errors and OpenAPI | Pass | Required/invalid/conflict/in-progress/indeterminate codes, response headers, 428, and request header schema pass. |
| A09 | Provider/Idempotency key containment | Pass | 17 security/artifact tests, 19 idempotency tests, and retained binary/evidence scans pass. |
| A10 | Non-destructive migration 0004 | Pass | Five migration tests plus live Volume schema show versions 1–4, new table/columns/index, and preserved old data. |
| A11 | Pure core regression safety | Pass | Full suite and deterministic TXT/EPUB2/EPUB3/image/CBZ samples pass with no GUI/browser gate. |
| A12 | Exact v0.3.1 Wheel | Pass | 132,544 bytes; SHA-256 `44ef868324c1f2d24868c3fe3efb8f4b443f0954d2dde9f4a386d05995fb5976`; 47 files. |
| A13 | Isolated extras matrix | Pass | Seven of seven install/`pip check`/dependency/offline-smoke environments pass. |
| A14 | Static checks, tests, and coverage | Pass | Ruff, strict mypy, compileall, 248 tests, and 84% branch-aware coverage pass. |
| A15 | Compose configurations | Pass | Compatibility and required-idempotency configurations parse with versioned image and hardened settings. |
| A16 | Hardened Docker build/live health | Pass | Image digest, candidate revision, UID 10001, read-only root, Volume, tmpfs, no-new-privileges, loopback port, health, 428, and cleanup verified. |
| A17 | Maintained documentation | Pass | Product/state/module/architecture/data-model/API/Docker/migration/release/security docs and ADR 0009 match implementation. |
| A18 | Complete versioned archive | Pass | Human/machine reports, command/environment, Wheel, samples, extras/migration/security/container evidence, and recursive checksums present. |

Required result: **18 Pass, 0 Fail, 0 Blocked, 0 Not executed**.

## Protocol summary

Covered operations:

```text
POST /api/projects
POST /api/profiles
POST /api/projects/{project_id}/jobs
POST /api/projects/{project_id}/segments/translate
POST /api/projects/{project_id}/rebuild
POST /api/jobs/{job_id}/retry
```

First success retains its normal 201/202/200 status and returns `Location` plus
`Idempotency-Replayed: false`. Completed replay returns 200 and
`Idempotency-Replayed: true`. Equivalent active Job coalescing returns 200 with
`X-Job-Coalesced: true`. In-progress responses include `Retry-After`. Pause/resume/cancel rely on
their existing state-machine idempotency.

## Migration and rollback

Migration `0004_service_idempotency.sql` adds nullable `jobs.execution_fingerprint` and
`jobs.request_id`, a partial unique index for matching active Jobs, and `idempotency_records`
unique by operation scope and key hash. Existing rows remain valid with null Job fields and are
not retroactively coalesced or rewritten.

Runtime users stop every writer and back up the entire data root or Docker Volume before upgrade.
Rollback restores that complete stopped pre-upgrade copy and runs v0.3.0 against it; there is no
in-place schema downgrade.

## Optional external and remote gates

| Category | Test | Status | Reason / next action |
| --- | --- | --- | --- |
| Optional external test | Real paid OpenAI-compatible Provider | Not executed | No paid credential or cost was authorized. |
| Optional external test | Real `manga-image-translator` model service | Not executed | External model/font/GPU operation remains separately deployed and licensed. |
| Optional external test | External `epubcheck` | Not executed | Built-in structure/reference/reopen validation passed. |
| Optional external test | Native Windows/WSL2 | Not executed | This run covered macOS arm64 and Linux/arm64 Docker. |
| Optional external test | Python 3.11, 3.13, and 3.14 hosts | Not executed | The local host ran 3.12.11; the declared CI matrix supplies later supplemental evidence. |

Optional result: **0 Pass, 0 Fail, 0 Blocked, 5 Not executed**. Mocks/fakes are not described as
real Provider or manga-model execution.

The candidate branch was not pushed by instruction, so remote CI for this exact target is
**Not executed by instruction**. At least one green target-commit CI run remains required before
claiming formal publication complete.

## Known limitations

- The optional runtime remains one host with SQLite and a local Artifact store; it is not a
  distributed queue or multi-host idempotency service.
- An interrupted synchronous external call is conservatively indeterminate because the service
  cannot prove whether the remote effect completed.
- Idempotency is scoped to the six documented operations. It is not authentication,
  authorization, billing, or business-level deduplication.
- Inputs remain TXT, common valid unencrypted EPUB 2/3, image, and CBZ/ZIP only.
- There is no GUI, user system, formal `novel-platform` dependency, PostgreSQL, Redis, broker,
  object store, or Kubernetes deployment surface.

## Harness and environment notes

- The first isolated PEP 517 build was blocked by sandbox network policy. The exact command passed
  after approved network access.
- The first container-start approval review disconnected and created no resource. The unchanged
  command passed after the user explicitly approved the exact disposable container.
- A read-only schema probe initially expected string migration versions; SQLite correctly returned
  integers. The corrected test assertion passed without a source change.
- `docker stop --time` emitted a deprecation warning but successfully stopped the container; the
  `--rm` container and named temporary Volume were then confirmed absent.

## Publication state

- Remote branch push: **Not executed by instruction**
- Merge to `main`: **Not executed by instruction**
- v0.3.1 tag creation/push: **Not executed by instruction**
- GitHub Release: **Not executed by instruction**
- Wheel/image publication: **Not executed by instruction**
- Server deployment: **Not executed by instruction**
- Release state: **release pending**

Publication requires separate authorization after this archive and the proposed final tag target
are reviewed.
