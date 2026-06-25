# Changelog

All notable changes to a2a-helper are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- `a2a-server` default `--host` switched from `127.0.0.1` to `0.0.0.0` so
  agents on other machines can connect out of the box. To restrict to
  loopback, pass `--host 127.0.0.1`. See SECURITY.md for implications.

## [0.1.0] - 2026-06-25

### Added
- HTTP+WebSocket hub backed by SQLite (`a2a.server`).
- Async Python client + interactive REPL (`a2a.client`).
- Echo demo worker (`a2a.echo_agent`) handling `echo` and `upper` task types.
- End-to-end smoke tests: register → task lifecycle → p2p over WS.
- P2P messages with HTTP fallback to inbox when recipient is offline.
- Agent Card registration with idempotent upsert.
- Presence events: `agent.online` / `agent.offline` broadcast over WS.
- Task events: `task.new` push to target, `task.done` push to originator.
- Console scripts: `a2a-server`, `a2a-client`, `a2a-echo`.
- MIT license, contributing guide, code of conduct, security policy.

### Notes
- No authentication, no TLS — single-user trusted network only.
- SQLite file at `~/.a2a/a2a.db` (WAL mode).

[Unreleased]: https://github.com/hubianluanma/a2a-helper/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/hubianluanma/a2a-helper/releases/tag/v0.1.0