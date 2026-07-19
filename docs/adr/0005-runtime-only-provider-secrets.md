# ADR 0005: Resolve Provider secrets only at runtime

- Date: 2026-07-19
- Status: Accepted

## Context

OpenAI-compatible translation needs an API key, but Jobs, configuration views, logs, Artifacts,
exports, fixtures, and database backups must remain safe to inspect. Building an encrypted secret
vault would add key-management claims that a local v0.1.0 tool cannot justify.

## Decision

Resolve Provider API keys from the process environment at the instant a Provider call begins.
The canonical variable is `LINGUASPINDLE_OPENAI_API_KEY`. Persist only non-secret base URL, model,
timeout, concurrency, and retry policy. Provider status reports a boolean `configured`, never the
key, authorization header, suffix, hash, or reversible derivative.

Central redaction filters known secret values and authorization-like fields before writing logs
or normalized errors. Jobs snapshot only the Translation Profile and non-secret Provider policy.
The HTTP API and GUI do not accept or return a raw key in v0.1.0.

## Consequences

- A restarted process must receive the key again through its environment or deployment secret
  mechanism.
- Docker Compose references an operator-supplied environment value; it does not bake a key into an
  image or example file.
- Key rotation needs no database rewrite.
- A future OS keychain integration would require a new ADR and must preserve the same serialization
  boundary.
