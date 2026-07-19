# Decisions

This is the index for durable product and technical decisions. Read a linked ADR before changing
the constraint it owns; use `docs/architecture.md` and `docs/data-model.md` for the current
consolidated design.

| ADR | Status | Decision and practical effect |
| --- | --- | --- |
| [0001 — No user system and loopback-default trust boundary](adr/0001-no-user-system-and-loopback-default.md) | Accepted | Keep all state instance-scoped, add no identity/ownership/auth model, open the GUI directly, bind locally by default, and place optional remote access control outside the application. |
| [0002 — Standalone modular monolith with one shared application core](adr/0002-standalone-shared-application-core.md) | Accepted | Keep LinguaSpindle independent from `novel-platform`; make Web, CLI, and API reuse one application/orchestration implementation across local, server, and Docker modes. |
| [0003 — Capability-driven Adapters and Artifact-identity data flow](adr/0003-capability-adapters-and-artifacts.md) | Accepted | Select external integrations by declared capability, keep upstream tools outside core, preserve immutable sources, and pass Artifact identities rather than machine-specific paths across layers. |
| [0004 — Python modular monolith, SQLite, and a durable in-process runner](adr/0004-python-modular-monolith-and-sqlite-runner.md) | Accepted | Use one Python application core, SQLite plus local Artifacts, forward-only migrations, and a restart-aware in-process worker shared by all interfaces. |
| [0005 — Runtime-only Provider secrets](adr/0005-runtime-only-provider-secrets.md) | Accepted | Resolve API keys from runtime environment only; persist and display no secret or secret derivative. |
| [0006 — manga-image-translator external Adapter](adr/0006-manga-image-translator-external-adapter.md) | Accepted | Integrate the GPL upstream only as an operator-managed HTTP service, distribute none of its uncertain weights/fonts, and test through a fake service. |

## Recording a decision

1. Add the next numbered file under `docs/adr/` (currently `0006`).
2. Record date, status, context, decision, and consequences.
3. Add a concise row here and update consolidated architecture/data-model/project context.
4. Supersede an accepted ADR with a new ADR when reversing it; do not rewrite history to hide the
   old decision.

Record decisions that constrain future work. Keep transient implementation notes, task progress,
and code-level mechanics out of ADRs.
