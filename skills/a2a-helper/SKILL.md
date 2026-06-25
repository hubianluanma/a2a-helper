---
name: a2a-helper
description: |
  Communicate with other AI agents through the local a2a-helper hub —
  send p2p messages, dispatch async tasks, list online agents, claim
  and submit tasks. Use when the user mentions "a2a", "a2a-helper",
  "agent hub", "send to <agent>", "tell <agent> to ...", "dispatch a
  task", "list agents", "task status", or "is <agent> online".
---

# a2a-helper

Local HTTP + WebSocket hub for inter-agent messaging and async tasks.
Any process that can speak HTTP+WS (Claude Code, Cursor, Aider, your own
scripts) registers as an agent and exchanges p2p messages or dispatches
tasks to other agents.

> Repo: https://github.com/hubianluanma/a2a-helper

## Hub

- HTTP base: `http://127.0.0.1:8765` (default — confirm with the user if unsure)
- WS:        `ws://127.0.0.1:8765`
- This session's agent id: `claude-main` (change if the user has a different setup)
- State:     `~/.a2a/a2a.db` (SQLite, WAL mode)
- Bind:      by default `0.0.0.0` (LAN-reachable). Use `--host 127.0.0.1`
  on untrusted networks.

## Endpoints

| Action                       | Method + path                                       | Body / params                                                 |
|------------------------------|-----------------------------------------------------|---------------------------------------------------------------|
| Register self                | `POST /v1/agents/register`                          | `{"id":"X","name":"Y","skills":[...]}` (idempotent)           |
| Send a p2p message           | `POST /v1/messages?from_agent=X`                    | `{"to_agent":"Y","content":{"text":"..."}}`                   |
| Read my inbox                | `GET  /v1/messages?agent=X&limit=N`                 | —                                                             |
| Dispatch a task              | `POST /v1/tasks?from_agent=X`                       | `{"to_agent":"Y","type":"T","input":{...}}`                   |
| List tasks                   | `GET  /v1/tasks?agent=Y&status=pending`             | filter by `status` (`pending` / `claimed` / `done`)           |
| Get task detail              | `GET  /v1/tasks/{id}`                               | returns `status` and `output`                                 |
| Claim a task                 | `POST /v1/tasks/{id}/claim?agent_id=Y`              | worker-side; sets status to `claimed`                         |
| Submit task result           | `POST /v1/tasks/{id}/result?agent_id=Y`             | `{"output":{...}}`; sets status to `done`                     |
| List online agents           | `GET  /v1/agents`                                   | `ws_active: true` means live                                  |
| Live events                  | `WS   /ws/{agent_id}`                               | server pushes `message`, `task.new`, `task.done`, `agent.online`, `agent.offline` |

## Decision: message vs task

| User says...                       | Use                                     |
|------------------------------------|-----------------------------------------|
| "Tell X ..." / "Send X a message"  | `POST /v1/messages` (fire-and-forget)   |
| "Give X a task to ..."             | `POST /v1/tasks` + poll until `done`    |
| "Did anyone message me?"           | `GET /v1/messages?agent=claude-main`    |
| "What's the status of task <id>?"  | `GET /v1/tasks/<id>`                    |
| "Who is online?"                   | `GET /v1/agents`                        |

A message has no result. A task has a result the worker returns via
`POST /v1/tasks/{id}/result`; the originator polls until `status == "done"`.

## Ready-to-paste templates

Always use `curl -s` and pipe JSON through `python3 -m json.tool` for readable
output. **Never run `a2a-client` interactively in a Bash tool call** — it's
a REPL and will hang.

```bash
# register self (idempotent — safe at the start of each session)
curl -s -X POST http://127.0.0.1:8765/v1/agents/register \
  -H 'Content-Type: application/json' \
  -d '{"id":"claude-main","name":"Claude Code","skills":["chat","code"]}'

# send a p2p message
curl -s -X POST 'http://127.0.0.1:8765/v1/messages?from_agent=claude-main' \
  -H 'Content-Type: application/json' \
  -d '{"to_agent":"alice","content":{"text":"start working"}}'

# dispatch a task and wait for the result
TID=$(curl -s -X POST 'http://127.0.0.1:8765/v1/tasks?from_agent=claude-main' \
  -H 'Content-Type: application/json' \
  -d '{"to_agent":"echo","type":"echo","input":{"msg":"ping"}}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["task_id"])')
while [ "$(curl -s http://127.0.0.1:8765/v1/tasks/$TID | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])')" != "done" ]; do sleep 0.5; done
curl -s http://127.0.0.1:8765/v1/tasks/$TID

# worker side: claim + execute + submit
TID=$(curl -s 'http://127.0.0.1:8765/v1/tasks?agent=claude-main&status=pending' \
  | python3 -c 'import sys,json;ts=json.load(sys.stdin);print(ts[-1]["id"] if ts else "")')
[ -z "$TID" ] && echo "no pending tasks" && exit 0
curl -s -X POST "http://127.0.0.1:8765/v1/tasks/$TID/claim?agent_id=claude-main"
# ... do the work ...
curl -s -X POST "http://127.0.0.1:8765/v1/tasks/$TID/result?agent_id=claude-main" \
  -H 'Content-Type: application/json' \
  -d '{"output":{"result":"..."}}'
```

The Python helper is also available in the project venv:

```bash
uv run -c "
from a2a.client import A2AClient
import asyncio
async def main():
    c = A2AClient('http://127.0.0.1:8765','ws://127.0.0.1:8765','claude-main','Claude Code')
    await c.register()
    await c.send_message('alice', {'text':'start working'})
asyncio.run(main())
"
```

## Don't

- Don't pass messages via shared files, `/tmp` drops, or ad-hoc HTTP servers
  — use the hub.
- Don't open raw WebSockets from inside a tool call — `a2a-client` CLI and
  `a2a.client.A2AClient` already manage the WS lifecycle.
- Don't run `a2a-client` interactively — it's a REPL, not a one-shot CLI.

## Setup status check

If a2a commands fail with `Connection refused`:

```bash
curl -sf http://127.0.0.1:8765/v1/agents >/dev/null && echo up || echo down
```

If `down`, start the hub (ask the user first if this is their machine):

```bash
nohup uv run -m a2a.server > ~/.a2a/hub.log 2>&1 &
```

## Cross-machine

If the hub runs on a different host, replace `127.0.0.1` with that host's
IP (e.g. `http://172.16.22.238:8765`). Make sure the hub's host firewall
allows the port — see [SECURITY.md](https://github.com/hubianluanma/a2a-helper/blob/main/SECURITY.md).