# Repository guidance

## Start here

For implementation, debugging, planning, review, refactoring, or repository
documentation work, use the repository-local `repo-context` skill first.

Before broad source inspection:

1. Read `docs/PROJECT_STATE.md` for the current milestone, implemented surface, and
   deliberate omissions.
2. Use `docs/MODULE_MAP.md` to find the responsible module, tests, migrations, and commands.
3. Read `docs/PRODUCT_SPEC.md` when the task affects product scope, acceptance, interfaces,
   deployment, or release requirements.
4. Read only the relevant parts of `docs/architecture.md` and `docs/data-model.md`.
5. Consult `docs/DECISIONS.md` and its linked ADRs before changing a durable boundary.
6. Inspect repository status, recent commits, and only the files directly related to the task.

Treat context documents as navigation aids, not substitutes for current code. Verify relevant
claims against implementation, migrations, tests, and generated contracts. Expand inspection
only when the maintained context is missing, stale, or inconsistent.

## Non-negotiable product boundaries

- Never add a user system: no registration, login, account, role, permission, tenant, member,
  ownership, quota, or collaboration model, and no identity-shaped fields or routes such as
  `user_id`, `owner_id`, `tenant_id`, `created_by`, `/api/users`, `/api/me`, or `/api/auth`.
- Keep LinguaSpindle standalone. It may later expose an API to `novel-platform`, but it must not
  depend on that repository, its database, its domain objects, or an identity supplied by it.
- Make Web GUI, CLI, and HTTP API call the same application layer and orchestration core. An
  interface must not run pipelines or third-party tools directly.
- Bind to loopback by default. Remote access belongs behind an explicitly configured reverse
  proxy, private network, Tailscale, Cloudflare Access, or equivalent perimeter; do not turn
  perimeter access control into an application user model.
- Keep imported sources immutable. Pass data between pipelines and adapters as Artifact
  identities, never as an implicit contract of machine-specific absolute paths.
- Select adapters by declared capability and configuration, never by product-name conditionals.
  Keep third-party tools outside the core repository and record code, model, and font licenses.
- Never expose API keys in database views, logs, job snapshots, artifacts, exports, fixtures, or
  error messages. Automated tests and demos must work with a Mock Provider and no paid key.

## Keep context current

After a change, update only context whose facts changed:

- `docs/PROJECT_STATE.md` for milestone, capability, scope, verification, deployment, or known-gap
  changes.
- `docs/MODULE_MAP.md` for new, removed, renamed, or repurposed modules, entry points, tests, and
  verification routes.
- `docs/architecture.md` for boundary, dependency, deployment, security, or data-flow changes.
- `docs/data-model.md` for persistent concepts, relationships, lifecycle, or invariant changes.
- `docs/PRODUCT_SPEC.md` only when the user explicitly changes the product or acceptance contract.
- `docs/DECISIONS.md` plus a new ADR for a durable technical or product decision. Supersede an
  accepted ADR with a new one rather than rewriting history.

Keep context concise and factual. Do not copy large source excerpts or transient task notes into
context documents.

## Verification

Run checks proportional to the changed surface and record real commands and outcomes. The
application stack and full quality gates have not yet been selected; update this section and
`docs/MODULE_MAP.md` when executable tooling is added. Until then, validate the repository-local
skill, check Markdown links and formatting, and inspect the final diff. Never invent a passing
result or weaken tests and acceptance criteria merely to make a gate pass.
