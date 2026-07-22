# Security policy

## Supported version

Security fixes target the latest published `0.3.0` release. The default branch may also contain
the unreleased v0.3.1 candidate; it is supported for development and acceptance, not represented
as a published release. This alpha software has not received an independent security audit.

## Reporting a vulnerability

Do not open a public issue containing an unpatched vulnerability, credentials, private source
material, or database/Artifact contents. Use the repository host's private security-advisory
facility to contact maintainers. Include affected version, reproduction, impact, and any proposed
mitigation. Maintainers should acknowledge a complete report within seven days, coordinate a fix
and disclosure, and credit the reporter if requested.

The project does not currently publish a dedicated security email. If no private reporting
facility is available, open a minimal public issue asking maintainers for a private contact method
without disclosing the vulnerability.

## Deployment boundary

LinguaSpindle intentionally has no login or authorization layer. Anyone with network access can
create/delete projects, run external capabilities, and download data. It binds to loopback by
default; Compose maps only to host loopback. Never publish the port directly to an untrusted
network. Put remote access behind an operator-managed private network, VPN, access proxy, or
equivalent perimeter.

This perimeter is operational infrastructure, not a LinguaSpindle user system.

## Secrets

- Supply `LINGUASPINDLE_OPENAI_API_KEY` through the runtime environment or deployment secret
  mechanism, never source control or an image layer.
- LinguaSpindle does not accept the key through its API and applies centralized redaction before
  persisting managed diagnostics, metadata, JSON/text Artifacts, and exports.
- Idempotency keys are caller credentials for retry correlation, not authentication. The service
  hashes them immediately and must never log, persist, export, or return their raw values.
- Avoid placing secrets in imported source files. An import containing the active runtime
  Provider key is rejected, but the application cannot classify every possible credential.
- Treat database backups, immutable Sources, Artifacts, external Adapter logs, and exports as
  sensitive content even when they contain no Provider key.

## Untrusted inputs and external tools

TXT, images, archives, upstream responses, and filenames are untrusted. The core bounds upload,
archive-member count, expanded size, and traversal; storage keys remain under one data root.
Operators should still apply host/container resource limits appropriate to their workload.

External manga services execute code and process documents outside the core trust boundary.
Install them deliberately, pin versions, review their network exposure and code/model/font
licenses, and do not assume LinguaSpindle's Apache-2.0 license covers them.

## Backups and deletion

Back up the complete configured data directory or Docker volume so SQLite metadata and Artifact
payloads remain consistent. Project deletion removes database records and bounded payload paths;
verify backups and retention requirements before confirming it.
