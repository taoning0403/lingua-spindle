---
name: repo-context
description: Orient work in the LinguaSpindle repository through maintained context documents before implementing, debugging, planning, reviewing, refactoring, researching, or documenting changes. Use at the start of repository development tasks, when locating responsible modules, checking product, architecture, data-model, security, Adapter, or acceptance constraints, and when refreshing repository context after a change.
---

# Repository context

Use maintained context to avoid broad repository scans while still verifying task-relevant facts
against current implementation.

## Orient

1. Read the root `AGENTS.md` completely.
2. Read `docs/PROJECT_STATE.md` for the current milestone, implemented capabilities, verification,
   deliberate omissions, and open decisions.
3. Use `docs/MODULE_MAP.md` to select the responsible code, tests, migrations, generated contracts,
   and commands. Treat paths explicitly marked planned as nonexistent until verified.
4. Read `docs/PRODUCT_SPEC.md` when the task touches product scope, interfaces, acceptance,
   deployment, licensing, test requirements, or release delivery.
5. Read only the relevant sections of `docs/architecture.md`, `docs/data-model.md`, and
   `docs/DECISIONS.md`; follow a linked ADR when the task touches its decision.
6. If Git is initialized, inspect `git status --short`, recent commits, and the directly responsible
   files. Preserve unrelated user changes.
7. Verify context claims against current code, migrations, generated contracts, tests, and runtime
   evidence before relying on them.
8. Expand the search only when context is missing, inconsistent, or insufficient to trace the
   affected behavior.

Avoid loading generated lockfiles, build output, full stylesheets, large Artifacts, or unrelated
modules unless the task requires them.

## Work and verify

- Enforce the permanent no-user-system, standalone-operation, shared-application-core, and
  loopback-default constraints in `AGENTS.md` and ADRs.
- Keep imported Sources immutable, pass data by Artifact identity, and select Adapters by declared
  capability rather than upstream-name conditionals.
- Inspect matching tests before changing behavior and run checks proportional to the changed
  surface. Report only commands actually run and their real outcomes.
- Reconcile documentation with implementation when they disagree; do not silently preserve stale
  context or invent unimplemented modules and gates.
- Compare the final diff with the product contract and context documents before declaring
  completion.

## Refresh context

Update only documents whose facts changed:

- Update `docs/PROJECT_STATE.md` when milestone, scope, capabilities, omissions, verification,
  deployment, or known blockers change.
- Update `docs/MODULE_MAP.md` when modules, entry points, ownership, tests, migrations, generated
  contracts, or verification routes change.
- Update `docs/architecture.md` or `docs/data-model.md` when boundaries, flows, storage,
  relationships, lifecycle, or invariants change.
- Update `docs/PRODUCT_SPEC.md` only when the user explicitly changes the product or acceptance
  contract; implementation progress belongs in `PROJECT_STATE.md`.
- Add a new ADR and update `docs/DECISIONS.md` for a durable decision. Supersede an accepted ADR
  with a new one rather than rewriting history to conceal a reversal.
- Skip context edits when implementation does not change any documented fact.

Keep context concise, factual, and free of large source excerpts, secrets, generated output, or
transient task notes.
