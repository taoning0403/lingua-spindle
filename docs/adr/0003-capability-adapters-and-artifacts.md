# ADR 0003: Capability-driven Adapters and Artifact-identity data flow

- Date: 2026-07-19
- Status: Accepted

## Context

Novel and manga translation depend on heterogeneous upstream tools with different commands,
containers, HTTP APIs, directories, progress, logs, GPU needs, and licenses. Binding Pipelines to
those details would spread vendor conditionals throughout business code. Passing local absolute
paths between layers would also make recovery, Docker, Windows/Linux parity, and a future remote
worker boundary fragile. Original imported sources must never be overwritten.

## Decision

Define a stable Adapter contract whose manifests declare capabilities, versions, invocation type,
formats, languages, GPU need, cancellation/progress/health support, configuration, upstream URL
and license, and modification status. Pipelines request capabilities and configured Adapter IDs;
application/orchestration code does not branch on an upstream product name. Adapter
implementations alone translate the contract into a local subprocess/CLI, independent container,
or HTTP service.

Represent every source, intermediate result, log/report, raw Adapter output, and final export as
an Artifact with stable identity, metadata, checksum, provenance, and private payload location.
Cross-layer contracts pass Artifact identities and typed metadata, not machine-specific paths.
A local Adapter runtime may resolve an Artifact to a private path at its boundary. Imported source
Artifacts are immutable; new work creates new Artifacts.

Keep upstream source, heavyweight models, GPU dependencies, and fonts outside the core repository
and core image. Record and verify code, model, and font licensing before selecting the first real
Adapter, and support mocks/contract tests without heavyweight downloads.

## Consequences

- Adapter manifests and contract tests become first-class extension and compatibility surfaces.
- Pipelines can substitute a Mock or a different tool with the same capability without changing
  domain logic.
- Storage must safely resolve private keys under the configured data root and publish payload plus
  metadata consistently.
- Raw upstream diagnostics remain available as redacted logs/Artifacts while stable errors and
  progress are normalized for GUI, CLI, and API.
- Future remote execution remains possible without implementing it in v0.1.0.
