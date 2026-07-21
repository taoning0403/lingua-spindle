# Decisions

This is the index for durable product and technical decisions. Read a linked ADR before changing
the constraint it owns; use `docs/architecture.md` and `docs/data-model.md` for the current
consolidated design.

| ADR | Status | Decision and practical effect |
| --- | --- | --- |
| [0001 — No user system and loopback-default trust boundary](adr/0001-no-user-system-and-loopback-default.md) | Accepted | Keep state instance-scoped, add no identity/ownership/auth model, bind optional HTTP locally by default, and place remote access control outside the application; ADR 0008 removes the former GUI reference. |
| [0002 — Standalone modular monolith with one shared application core](adr/0002-standalone-shared-application-core.md) | Accepted, partly superseded by 0008 | Keep LinguaSpindle independent from `novel-platform` and keep one business implementation; ADR 0008 makes the pure core the shared boundary and replaces the GUI-centric interface set. |
| [0003 — Capability-driven Adapters and Artifact-identity data flow](adr/0003-capability-adapters-and-artifacts.md) | Accepted; data-flow detail partly superseded by 0008 | Select external integrations by declared capability, keep upstream tools outside core, and preserve immutable sources. Artifact identities remain the optional-runtime persistence contract; the pure core accepts caller-owned paths/streams/bytes and typed manifests/results. |
| [0004 — Python modular monolith, SQLite, and a durable in-process runner](adr/0004-python-modular-monolith-and-sqlite-runner.md) | Accepted for optional runtime; partly superseded by 0008 | Retain SQLite, local Artifacts, forward-only migrations, and explicit restart-aware runner as an extra; frameworks/runtime are no longer the default core. |
| [0005 — Runtime-only Provider secrets](adr/0005-runtime-only-provider-secrets.md) | Accepted, key-source detail superseded by 0008 | Persist/display no secret or derivative; inject credentials from the caller at runtime, with environment resolution limited to optional interfaces. |
| [0006 — manga-image-translator external Adapter](adr/0006-manga-image-translator-external-adapter.md) | Accepted | Integrate the GPL upstream only as an operator-managed HTTP service, distribute none of its uncertain weights/fonts, and test through a fake service. |
| [0007 — Structure-preserving EPUB round trip and bounded archive processing](adr/0007-epub-round-trip-and-bounded-archive-processing.md) | Accepted | Extend the existing Source/Segment/Artifact pipeline with stable EPUB text locators, deterministic reuse, source-based reconstruction, independent validation, streamed payload I/O, and centralized ZIP resource guards. |
| [0008 — Headless, library-first orchestration core](adr/0008-headless-library-first-orchestration-core.md) | Accepted | Make the pure typed TXT/EPUB/manga core the default public boundary; move persistence and interfaces to extras, remove the GUI, and retain v0.2 data through migration 0003. |

## Recording a decision

1. Add the next numbered file under `docs/adr/` (currently `0008`).
2. Record date, status, context, decision, and consequences.
3. Add a concise row here and update consolidated architecture/data-model/project context.
4. Supersede an accepted ADR with a new ADR when reversing it; do not rewrite history to hide the
   old decision.

Record decisions that constrain future work. Keep transient implementation notes, task progress,
and code-level mechanics out of ADRs.
