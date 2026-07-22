# ADR 0009: Durable server idempotency and request correlation

- Date: 2026-07-22
- Status: Accepted

## Context

The optional HTTP service can create persistent resources and invoke Providers. A caller retry
after a timeout or lost response could therefore create duplicate Projects, Jobs, translation
Artifacts, or Provider work. Process-local locks cannot protect retries across restarts or two
service instances sharing one SQLite data root. The service also needs one safe correlation value
across HTTP responses, application logs, Jobs, and Step logs without retaining caller secrets.

This is service hardening, not a user/account boundary. The pure TXT/EPUB/manga core remains
side-effect-free and unaware of HTTP headers, SQLite, and idempotency records.

## Decision

1. The six persistent or Provider-triggering POST operations accept `Idempotency-Key`: Project
   creation, Profile creation, Job creation, selected translation, rebuild, and Job retry.
   Compatibility mode accepts a missing key. Setting
   `LINGUASPINDLE_REQUIRE_IDEMPOTENCY_KEY=true` rejects a missing key with HTTP 428.
2. A key is 8–128 characters from letters, digits, `.`, `_`, `:`, and `-`. The server hashes it
   with SHA-256 immediately and persists only `(operation scope, key hash)`. Raw keys are never
   stored or logged.
3. Each operation computes a versioned SHA-256 request fingerprint over canonical, normalized
   semantics. Reusing a key with the same fingerprint returns the retained resource; reusing it
   for different semantics is a stable conflict. Caller text is represented in the idempotency
   table only by a normalized hash.
4. Migration `0004_service_idempotency.sql` adds durable `processing`, `completed`, `failed`, and
   `indeterminate` records with a database uniqueness constraint on `(scope, key_hash)`. Startup
   turns abandoned `processing` records into `indeterminate`; it never guesses whether an
   interrupted external side effect completed.
5. Successful first responses retain their operation status. A completed replay returns HTTP
   200 with `Idempotency-Replayed: true`; a live claim, changed fingerprint, or indeterminate
   result returns a stable HTTP 409 error. In-progress responses include `Retry-After`.
6. Job execution fingerprints include the immutable source identity/checksum, Pipeline key and
   version, effective Profile snapshot, Provider/model and non-secret configuration, Adapter
   configuration, and language pair. A partial SQLite unique index permits only one matching
   active Job in `queued`, `running`, `paused`, or `cancelling`. A request that joins that Job
   returns it with `X-Job-Coalesced: true`. Terminal Jobs release the active uniqueness slot.
7. Project upload publication and its idempotency record share one database transaction after
   bounded staging. A concurrent loser removes its staged payload, so a duplicate request cannot
   leave a second Project or orphan Artifact.
8. Every HTTP response carries `X-Request-ID`. A safe caller value is preserved; otherwise the
   service generates a UUID. The first Job request ID is stored on the Job and copied into Step
   log details. Request IDs may be logged, but raw idempotency keys and Provider keys may not.
9. Pause, resume, and cancel keep their natural state-machine idempotency and do not require an
   idempotency record. Persistent concurrency safety is owned by SQLite constraints and
   transactions, not only process-local synchronization.

## Consequences

- Callers can safely retry the covered operations after network uncertainty and can correlate
  server responses with durable work.
- Synchronous Provider interruption is intentionally conservative: a subsequent retry receives
  `IDEMPOTENCY_INDETERMINATE` until an operator/caller chooses a new key after reconciliation.
- Idempotency metadata is instance-local operational state. It adds no identity, ownership,
  quota, tenant, or authorization concept.
- SQLite remains the supported one-host persistence boundary. This decision does not introduce a
  broker, distributed lock service, PostgreSQL, Redis, or coupling to a calling product.
