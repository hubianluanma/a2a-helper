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

## Configuration — edit these 4 lines, nothing else

All templates below reference these shell variables. Change them once at
the top of your session (or in your shell rc) and every command adapts:

```bash
A2A_HOME=/path/to/a2a-helper        # local clone of the repo; only needed for commands that run a2a-* binaries (start hub, spawn workers). Skip if `a2a-server` / `a2a-client` / `a2a-echo` are already on PATH (e.g. after `uv tool install a2a-helper`).
HUB_HTTP=http://127.0.0.1:8765      # hub HTTP base (change to e.g. http://192.168.1.10:8765 for cross-machine)
HUB_WS=ws://127.0.0.1:8765          # WS base, same host as HUB_HTTP
AGENT_ID=claude-main                # this session's agent id (change per session/instance)
```

If you'd rather not export them, paste them at the top of each snippet
before running.

**Which variables are required for which commands:**

| Command kind                         | Needs                  |
|--------------------------------------|------------------------|
| Pure HTTP calls (send, dispatch, list, claim, submit, status) | `HUB_HTTP`, `AGENT_ID` |
| Local `a2a-server` / `a2a-client` / `a2a-echo` | + `A2A_HOME` |
| Pure WS events                       | `HUB_WS`               |

So if you only want to *talk* to a hub running on another host, set just
`HUB_HTTP` / `HUB_WS` / `AGENT_ID` — you don't need `a2a-helper` checked
out locally at all.

Other facts (rarely need to change):

- State DB: `~/.a2a/a2a.db` (SQLite, WAL mode) — only on the host running the hub
- Default bind: `0.0.0.0` (LAN-reachable). Pass `--host 127.0.0.1` on
  untrusted networks.

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

| User says...                       | Use                                                  |
|------------------------------------|------------------------------------------------------|
| "Tell X ..." / "Send X a message"  | `POST $HUB_HTTP/v1/messages` (fire-and-forget)       |
| "Give X a task to ..."             | `POST $HUB_HTTP/v1/tasks` + poll until `done`        |
| "Did anyone message me?"           | `GET $HUB_HTTP/v1/messages?agent=$AGENT_ID`          |
| "What's the status of task <id>?"  | `GET $HUB_HTTP/v1/tasks/<id>`                        |
| "Who is online?"                   | `GET $HUB_HTTP/v1/agents`                            |

A message has no result. A task has a result the worker returns via
`POST /v1/tasks/{id}/result`; the originator polls until `status == "done"`.

## Ready-to-paste templates

All snippets assume `$HUB_HTTP` / `$HUB_WS` / `$AGENT_ID` are set (top of
file). Always use `curl -s` and pipe JSON through `python3 -m json.tool` for
readable output. **Never run `a2a-client` interactively in a Bash tool
call** — it's a REPL and will hang.

```bash
# register self (idempotent — safe at the start of each session)
curl -s -X POST $HUB_HTTP/v1/agents/register \
  -H 'Content-Type: application/json' \
  -d "{\"id\":\"$AGENT_ID\",\"name\":\"Claude Code\",\"skills\":[\"chat\",\"code\"]}"

# send a p2p message
curl -s -X POST "$HUB_HTTP/v1/messages?from_agent=$AGENT_ID" \
  -H 'Content-Type: application/json' \
  -d '{"to_agent":"alice","content":{"text":"start working"}}'

# dispatch a task and wait for the result
TID=$(curl -s -X POST "$HUB_HTTP/v1/tasks?from_agent=$AGENT_ID" \
  -H 'Content-Type: application/json' \
  -d '{"to_agent":"echo","type":"echo","input":{"msg":"ping"}}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["task_id"])')
while [ "$(curl -s $HUB_HTTP/v1/tasks/$TID | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])')" != "done" ]; do sleep 0.5; done
curl -s $HUB_HTTP/v1/tasks/$TID

# worker side: claim + execute + submit
TID=$(curl -s "$HUB_HTTP/v1/tasks?agent=$AGENT_ID&status=pending" \
  | python3 -c 'import sys,json;ts=json.load(sys.stdin);print(ts[-1]["id"] if ts else "")')
[ -z "$TID" ] && echo "no pending tasks" && exit 0
curl -s -X POST "$HUB_HTTP/v1/tasks/$TID/claim?agent_id=$AGENT_ID"
# ... do the work ...
curl -s -X POST "$HUB_HTTP/v1/tasks/$TID/result?agent_id=$AGENT_ID" \
  -H 'Content-Type: application/json' \
  -d '{"output":{"result":"..."}}'
```

The Python helper is also available in the project venv:

```bash
uv run -c "
from a2a.client import A2AClient
import asyncio
async def main():
    c = A2AClient('$HUB_HTTP', '$HUB_WS', '$AGENT_ID', 'Claude Code')
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
curl -sf $HUB_HTTP/v1/agents >/dev/null && echo up || echo down
```

If `down`, start the hub (ask the user first if this is their machine):

```bash
nohup uv --directory $A2A_HOME run -m a2a.server > ~/.a2a/hub.log 2>&1 &
```

If the hub is already running elsewhere (e.g. on `172.16.22.238`), just set
`HUB_HTTP` to that address — you don't need to start one locally.

## Spawn a worker on this machine

To run a worker that registers and processes tasks (e.g. `echo_agent`,
handles tasks of type `echo` / `upper`):

```bash
nohup uv --directory $A2A_HOME run -m a2a.echo_agent --id $AGENT_ID > ~/.a2a/$AGENT_ID.log 2>&1 &
```

For a custom worker, write your own Python that uses `a2a.client.A2AClient`
(see the 10-line pattern in the project README) and run it the same way.
Workers only need `HUB_HTTP` / `HUB_WS` / `AGENT_ID`; they don't need a
copy of the code at any specific path beyond the `uv --directory` invocation.

## Cross-machine

Change the top-of-file `HUB_HTTP` (and `HUB_WS`) to the host where the hub
runs, e.g.:

```bash
HUB_HTTP=http://172.16.22.238:8765
HUB_WS=ws://172.16.22.238:8765
```

All templates below adapt automatically. Make sure the hub's host firewall
allows the port — see [SECURITY.md](https://github.com/hubianluanma/a2a-helper/blob/main/SECURITY.md).