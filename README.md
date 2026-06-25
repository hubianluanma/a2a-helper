# a2a-helper

[🇺🇸 English](README.md) · [🇨🇳 简体中文](README.zh.md)

[![CI](https://img.shields.io/github/actions/workflow/status/hubianluanma/a2a-helper/ci.yml?branch=main&label=CI)](https://github.com/hubianluanma/a2a-helper/actions)
[![PyPI](https://img.shields.io/pypi/v/a2a-helper)](https://pypi.org/project/a2a-helper/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/a2a-helper)](https://pypi.org/project/a2a-helper/)

A lightweight agent-to-agent hub. Any process that can speak HTTP + WebSocket
(Claude Code, Aider, Cursor, your own scripts) registers as an agent and then
exchanges **p2p messages** in real time or **dispatches tasks** asynchronously.

Inspired by the [A2A Protocol](https://github.com/google/a2a-protocol)
(`AgentCard` / `Task` / `Artifact` / `Message`), trimmed to ~300 LOC, single
SQLite file, zero external services.

> ⚠️ Package name is `a2a-helper` on PyPI to avoid colliding with
> `google/a2a`. The import name in code stays `a2a` (matches the directory).

## Install

Dependencies are managed with [uv](https://docs.astral.sh/uv/) (`uv ≥ 0.4`).
`pyproject.toml` is the single source of truth; `uv.lock` pins exact versions.

From this checkout (development mode, includes dev extras):

```bash
git clone https://github.com/hubianluanma/a2a-helper
cd a2a-helper
uv sync --all-extras --dev      # creates .venv/ with runtime + dev deps
```

Published releases (once uploaded to a registry):

```bash
uvx a2a-server --port 8765      # run without installing, like npx
# or
uv tool install a2a-helper      # install CLI as global commands
```

> Don't have uv? `pip install -e ".[dev]"` still works — `pyproject.toml` is
> a standards-compliant build descriptor, not uv-specific.

## Quick start

```bash
# terminal 1: the hub
a2a-server --port 8765

# terminal 2: an echo worker
a2a-echo --id echo

# terminal 3: an interactive client
a2a-client --id claude-1 --name Claude --skills chat,code
```

State lives at `~/.a2a/a2a.db` (SQLite, WAL mode, safe under concurrent readers).

By default the hub binds to `0.0.0.0:8765` so any host that can reach your
machine on port 8765 can connect — useful for cross-machine setups. To
restrict to loopback (single-machine only), pass `--host 127.0.0.1`. See
[`SECURITY.md`](SECURITY.md) before exposing it on a shared network.

## What you get

- **Real-time p2p**: messages pushed over WebSocket if the recipient is online;
  otherwise queued in their inbox (`GET /v1/messages?agent=X`).
- **Async tasks**: dispatch a `Task` to another agent; they claim → execute →
  submit output. Status is queryable; results push back to the originator.
- **Presence**: `agent.online` / `agent.offline` events broadcast on connect.
- **AgentCard**: each agent registers `id` + `name` + `skills[]` (skills are
  metadata only — the hub does no routing by skill).

## Protocol at a glance

```http
POST /v1/agents/register         {"id":"claude-1","name":"Claude","skills":["chat","code"]}
POST /v1/messages?from_agent=X   {"to_agent":"echo","content":{"text":"hi"}}
POST /v1/tasks?from_agent=X      {"to_agent":"echo","type":"echo","input":{"msg":"ping"}}
GET  /v1/tasks/{id}                                      # → status, output
POST /v1/tasks/{id}/claim?agent_id=X                     # pull-style
POST /v1/tasks/{id}/result?agent_id=X    {"output":{...}}
WS   /ws/{agent_id}                                      # push events
```

Full reference: see [`docs/CURSOR_USAGE.md`](docs/CURSOR_USAGE.md) — it uses
Cursor as the running example but the protocol is agent-agnostic.

## Wire your own agent in 10 lines

```python
from a2a.client import A2AClient

async def main():
    a = A2AClient("http://127.0.0.1:8765", "ws://127.0.0.1:8765",
                  "my-agent", "My Agent", skills=["summarize"])
    await a.register(); await a.connect_ws()
    while True:
        t = await a.claim()
        if not t: await asyncio.sleep(0.5); continue
        result = await handle(t["type"], t["input"])
        await a.submit(t["id"], result)
```

## Project layout

```
a2a/                # the package (import name `a2a`)
  server.py         # FastAPI hub, SQLite, HTTP + WS
  client.py         # async client lib + REPL CLI
  echo_agent.py     # demo worker
tests/              # smoke tests (spawn-on-free-port pattern)
docs/               # usage guides
```

## Development

```bash
uv run ruff check .        # lint
uv run ruff format .       # autoformat
uv run pytest              # all 3 smoke tests must pass
```

CI runs the same three commands on every PR. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) for the full workflow.

## Teach your AI client about a2a

Drop one of these into **your project's** root so Cursor / Claude Code knows
the hub exists and how to call it without you explaining every time:

```bash
# for Cursor
cp examples/cursorrules /path/to/your/project/.cursorrules

# for Claude Code
cp examples/CLAUDE.md /path/to/your/project/CLAUDE.md
```

Edit the `agent id` and hub address at the top if your setup differs from the
defaults. Both files list the endpoints, when to use messages vs tasks, and
ready-to-paste `curl` templates.

## Documentation

- [`docs/CURSOR_USAGE.md`](docs/CURSOR_USAGE.md) — end-to-end usage with Cursor
  as the example agent
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev workflow, commit conventions
- [`CHANGELOG.md`](CHANGELOG.md) — version history (Keep-a-Changelog format)
- [`SECURITY.md`](SECURITY.md) — how to report vulnerabilities
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) — Contributor Covenant 2.1

## Status & scope

Pre-1.0. Use it on a single host with trusted agents; add a reverse proxy for
anything beyond. The hub itself ships **no auth, no TLS, no clustering** —
these are deliberate omissions called out in the [docs](docs/CURSOR_USAGE.md#9-它没做的事按需自加).

## License

[MIT](LICENSE).

---
