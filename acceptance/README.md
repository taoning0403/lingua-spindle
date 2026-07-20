# Acceptance archive

This directory preserves versioned LinguaSpindle acceptance records. Each released or candidate
version has its own directory so historical execution evidence is not mixed with later results.

## Layout

- `reports/` contains human-readable acceptance, supplemental, and publication conclusions.
- `evidence/` contains machine-readable reports, command transcripts, environment records,
  checksums, and generated inventories.
- `artifacts/` is the version-local landing area for small, safe fixtures and generated outputs.

Text reports, compact redacted evidence, deterministic test fixtures, and checksums may be tracked
in Git. Large binaries, browser traces, screenshots containing source material, runtime databases,
paid-Provider outputs, and temporary build products are not committed by default. Their checksums
and provenance belong in `evidence/`; publishable binaries may instead be retained as immutable
GitHub Release assets.

Acceptance scripts and commands must write into the matching version directory, never the
repository root. Reports distinguish `Pass`, `Fail`, `Blocked`, `Not executed`, and
`Optional external test`; a later supplemental run may supersede an earlier blocker only when the
original result remains visible and the later evidence is linked.

## Versions

- [v0.1.0](v0.1.0/README.md) — accepted and published WSL2/Linux Technical Preview.
- `v0.2.0/` — created by the v0.2.0 acceptance run; candidate evidence must remain separate from
  v0.1.0.
