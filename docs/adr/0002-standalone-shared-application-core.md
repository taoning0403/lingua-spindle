# ADR 0002: Standalone modular monolith with one shared application core

- Date: 2026-07-19
- Status: Accepted

## Context

LinguaSpindle must support Web GUI, CLI, and HTTP automation on Windows, Linux, servers, Docker,
and non-Docker hosts. It may eventually be called by `novel-platform`, but sharing internal data
or implementation would make either program a deployment prerequisite for the other. Separate
business logic per interface or environment would produce inconsistent Job behavior and recovery.

## Decision

Build LinguaSpindle as a standalone modular monolith with explicit interface, application,
orchestration, Adapter/Provider, and persistence/storage boundaries. Web GUI, CLI, and HTTP API
will call the same application services and orchestration core over the same durable state. They
will not execute Pipelines or third-party tools directly.

Use the same business implementation in local, server, Docker, Windows, and Linux modes. Limit
environment-specific code to infrastructure adapters such as process launching, paths, and server
startup. Do not require `novel-platform`, share its database, import its internal domain model,
accept its identity as a prerequisite, or modify its data. A future relationship is an ordinary
versioned HTTP API integration between independent programs.

Concrete frameworks and package layout remain open until evaluated and recorded separately.

## Consequences

- Cross-interface tests must prove that GUI/CLI/API observe and control the same Jobs and data.
- Interface handlers remain thin; application and orchestration behavior is testable without a
  browser or live HTTP server.
- Deployment stays simple enough for one host and does not introduce microservices merely to
  mirror architectural layers.
- A future `novel-platform` client uses public API contracts and cannot bypass LinguaSpindle's Job,
  Artifact, or configuration rules.
