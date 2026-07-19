# ADR 0001: No user system and loopback-default trust boundary

- Date: 2026-07-19
- Status: Accepted

## Context

LinguaSpindle is a single-instance translation tool intended for local Windows/Linux use and
operator-controlled server/Docker deployment. A built-in login system would imply identities,
ownership, permissions, recovery, sessions, and a public-service security posture that the
product explicitly does not need. Speculative identity fields would also contaminate every domain
and migration even if no login UI were shipped.

Server deployment still needs a safe trust boundary because project, model configuration, Jobs,
and files are sensitive and operationally powerful.

## Decision

LinguaSpindle will never build an application user system. It will have no registration, login,
account, administrator, ordinary user, role, permission, organization, tenant, membership,
ownership, quota, collaboration, or per-user state. Domain/API/schema names such as `user_id`,
`owner_id`, `tenant_id`, `created_by`, `/api/users`, `/api/me`, and `/api/auth` are prohibited.
All state belongs directly to the running LinguaSpindle instance, and the GUI opens directly to
the tool.

The server binds to loopback by default. Documentation will say not to expose it directly to the
public Internet. An operator who needs remote access must deliberately place it behind a reverse
proxy, private network, Tailscale, Cloudflare Access, VPN, or equivalent external perimeter. Any
identity or policy in that perimeter remains outside LinguaSpindle and is not copied into its
domain model.

## Consequences

- Anyone with network reachability can operate the instance; safe network placement is mandatory.
- Domain objects, logs, exports, and Artifacts need no owner/member foreign keys or authorization
  filters.
- GUI, CLI, and API need no authentication flows, account pages, session storage, or permission
  tests.
- Multi-user SaaS or collaboration would be a different product boundary, not a hidden extension
  to pre-model now.
- Security work still covers input validation, archive/path safety, secret redaction, subprocess
  isolation, safe defaults, and deployment documentation.
