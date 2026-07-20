# ADR 0007: Structure-preserving EPUB round trip and bounded archive processing

- Date: 2026-07-20
- Status: Accepted

## Context

v0.2.0 must translate common EPUB 2/3 books without flattening them to plain text, breaking links
or resources, introducing a second task model, or allowing hostile ZIP packages to consume
unbounded local resources. EPUB has both XML text semantics and an archive/package graph; a
successful translation must preserve that graph while associating each translation with an exact
source location.

The existing architecture already owns immutable Sources, Artifact identities, durable ordered
Jobs/Steps, TranslationSegments, Providers, QA, retry/recovery, and a local atomic payload store.
Those boundaries should be extended, not replaced. The runtime must also remain dependency-light,
offline-testable, and usable through Web, CLI, and API.

## Decision

1. Add `novel_epub_v1` as a code-defined Pipeline Preset in the existing orchestration engine.
   EPUB Projects remain `kind=novel`; the immutable Source records `kind=epub`, and Source kind
   selects a compatible Pipeline deterministically.
2. Inspect EPUB into a JSON-compatible manifest containing package/resource structure and ordered
   visible-text units. Each unit has a stable source document and XML-slot locator. Persist its
   lineage and input hashes on the existing TranslationSegment record.
3. Reuse a prior successful Segment only when the complete immutable content location and
   effective non-secret translation input hash match. Do not add fuzzy matching or a general
   translation-memory subsystem.
4. Rebuild from the immutable source archive. Apply translations only to declared text slots;
   preserve failed/missing slots with source text. Keep all unmodified resource payloads byte-
   identical, update OPF and XHTML/navigation target-language declarations, and publish a new
   Artifact rather than overwriting the Source.
5. Validate the generated temporary EPUB independently before publication by reopening it,
   checking package/reference invariants, re-inspecting it, and comparing unchanged payloads.
   External validators remain optional acceptance tools rather than runtime dependencies.
6. Parse uploaded XHTML/XML as data and never render it directly as trusted GUI markup. Do not
   translate scripts, styles, paths, URLs, anchors, identifiers, or structural markup.
7. Reject encryption metadata and do not decrypt, bypass DRM, or de-obfuscate protected assets.
8. Centralize upload bytes, member count, total expansion, per-member expansion, compression ratio,
   and member-path depth in runtime Settings. Validate path safety, duplicate portable names,
   symlinks, compression, and both announced/observed sizes before Project publication.
9. Stream Source publication, Artifact HTTP downloads, and CLI Artifact copies. Temporary output
   must be atomically replaced or removed on failure. Keep SQLite and the one local Artifact store;
   no broker, object store, or distributed worker is introduced.

## Consequences

- EPUB participates in the same controls, error vocabulary, logs, Provider behavior, QA, restart
  classification, deletion, backup, and no-user trust boundary as TXT and manga.
- Imported sources and non-text resources remain auditable, while XML documents intentionally
  modified by translation may be semantically equivalent but serialized differently.
- Segment reuse is deterministic and conservative; policy changes cause retranslation rather than
  risking stale output.
- Valid but unusual publisher packages outside the documented EPUB 2/3 subset can be rejected.
  Protected content is unsupported by design.
- Large-book operation remains bounded on one host. Operators raising limits are responsible for
  matching disk, `/tmp`, reverse-proxy, Provider-cost, and processing-time budgets.
- Forward-only migration `0002_epub.sql` extends existing records without invalidating v0.1.0
  Projects, Jobs, Sources, or Artifacts.
