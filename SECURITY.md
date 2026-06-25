# Security Policy

## Supported versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: yes |

The project is pre-1.0 — only the latest minor release receives security
fixes. Bump the major on breaking security changes.

## Reporting a vulnerability

**Do not open a public GitHub issue.** Email **`<hubianluanma@gmail.com>`** with:

1. A description of the issue and its impact
2. Steps to reproduce, or a proof-of-concept
3. Affected version(s)

You'll get an acknowledgement within 72 hours. We'll work out a fix timeline
before any public disclosure.

## Scope

In scope:

- Anything that allows one agent to impersonate another or read/write another
  agent's data without going through the registered owner.
- Anything that lets an unauthenticated client crash the hub, corrupt the DB,
  or execute arbitrary code on the host.
- TLS / transport-level concerns if we ever ship TLS in-package.

Out of scope:

- Issues that require a trusted agent to misbehave (the hub trusts registered
  agents — that's by design).
- Auth bypasses when the deployment has no auth turned on (default is no auth
  for local development; production deployments must front the hub with a
  reverse proxy that adds auth).

## Hardening checklist (for deployment)

The hub itself does not provide auth/TLS. For anything beyond a single-user
laptop, deploy behind a reverse proxy that:

- Terminates TLS (nginx, Caddy, Traefik, Cloudflare Tunnel, ...)
- Enforces an allow-list of agent IDs or runs an auth proxy in front of `/v1/*`
- Rate-limits `/v1/agents/register` to prevent agent-ID squatting
- Restricts `/ws/*` to authenticated upgrades

Future versions may add a built-in auth layer; track
[issues](https://github.com/hubianluanma/a2a-helper/issues) for the `auth` label.
