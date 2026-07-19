# ADR 0006: manga-image-translator as a process-separated external Adapter

- Date: 2026-07-19
- Status: Accepted

## Context

The first manga integration needs maintained automation, whole-image output, batch suitability,
CPU and GPU options, and a mockable protocol. Candidate research also found material license and
packaging differences.

## Decision

Select `zyddnys/manga-image-translator` at researched commit `efdc229d` as the first real Adapter,
using its separately operated HTTP service. The Adapter advertises `manga_full_pipeline`, accepts
image Artifacts, and emits final-image plus raw-response Artifacts. Configuration selects it by
capability and Adapter ID, never by product-name branches in application or orchestration code.

Do not vendor, import, install, or silently download upstream code, containers, models, or fonts.
The upstream GPL-3.0-only program remains a separate work. Because the inspected upstream snapshot
does not contain a complete per-weight and per-font license inventory, LinguaSpindle does not
redistribute any of those assets and labels that review incomplete.

The v0.1.0 HTTP implementation treats progress and immediate cancellation as unsupported even
though upstream offers a streaming protocol. Cancellation completes at the next safe image
boundary. Contract tests use a local fake HTTP service and never download models.

## Consequences

- Operators install, configure, license, and secure the external service themselves.
- Missing service configuration produces a stable `ADAPTER_UNAVAILABLE` diagnostic in GUI, CLI,
  and API.
- GPL source and uncertain model/font terms do not become licenses of LinguaSpindle's Apache-2.0
  core, but they remain obligations for the operator's separate upstream deployment.
- Streaming progress or subprocess support can be added behind the same capability contract after
  compatibility and cancellation semantics are tested.
