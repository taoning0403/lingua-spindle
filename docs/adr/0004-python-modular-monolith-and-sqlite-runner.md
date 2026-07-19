# ADR 0004: Python modular monolith, SQLite, and a durable in-process runner

- Date: 2026-07-19
- Status: Accepted

## Context

v0.1.0 needs one implementation shared by HTTP, CLI, and Web; durable restart behavior; simple
Windows/Linux/Docker startup; and a real OpenAI-compatible client without Redis, a broker, or a
distributed worker system. The mandatory offline path should remain small enough to understand
and test as a state machine.

## Decision

Use Python 3.11+ for the packaged modular monolith. FastAPI/Uvicorn provide HTTP and OpenAPI,
Typer provides the CLI, SQLAlchemy 2 manages relational access, and SQLite in WAL mode is the
single metadata database. Package-owned forward-only SQL migrations create and evolve the
schema. Large payloads use an atomic local Artifact store under one configurable data root.

Run ordered Pipelines through a durable in-process polling worker. A compare-and-update claim in
SQLite ensures that only one local runner claims a queued Job. Lifecycle transitions and Step
outputs are committed at safe boundaries. Startup classifies interrupted `running` Steps as
failed with a stable recovery error; retry reuses succeeded Step outputs and preserves prior
attempt logs.

The Web GUI is a no-login, server-served ES-module application over the HTTP API. It uses polling
as the sole v0.1.0 progress transport, avoiding a separate Node runtime and three competing
real-time mechanisms.

## Consequences

- GUI, CLI, and API instantiate the same application services over the same database and Artifact
  store.
- One host and one data root are the supported scheduling boundary. SQLite write contention is
  bounded and visible; this is not a distributed runner.
- A process crash may fail the active Step, but completed Steps remain reusable and the Job is
  explicitly retryable.
- Static browser assets need no production build tool, while browser behavior still receives
  Playwright coverage.
- A future database or worker change requires a new ADR and migration plan rather than unused
  abstractions now.
