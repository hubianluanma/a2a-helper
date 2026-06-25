# Drop this file at your project root as `CLAUDE.md` so Claude Code knows
# how to talk to a2a-helper. Adjust the agent id and hub address below if
# your setup differs.

# a2a-helper

This project uses [a2a-helper](https://github.com/hubianluanma/a2a-helper),
a local HTTP+WebSocket hub for inter-agent messaging and async tasks. Use it
instead of writing scratch files, ad-hoc HTTP servers, or any other manual
channel to talk to other AI agents (Cursor, Aider, other Claude Code sessions).

## Hub

- HTTP base: `http://127.0.0.1:8765` (default — confirm with the user if unsure)
- WS:        `ws://127.0.0.1:8765`
- This session's agent id: `claude-main` (change if the user has a different setup)
- DB / state: `~/.a2a/a2a.db`
- Bind: by default `0.0.0.0` (LAN-reachable) — pass `--host 127.0.0.1` to restrict

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
| Submit task result           | `POST /v1/tasks/{id}/result?agent_id=Y`             | `{"output":{...}}`; sets status to `done`                    |
| List online agents           | `GET  /v1/agents`                                   | `ws_active: true` means live                                  |
| Live events                  | `WS   /ws/{agent_id}`                               | server pushes `message`, `task.new`, `task.done`, `agent.online`, `agent.offline` |

## When to use what

- "Tell X ..." / "Send X a message" → `POST /v1/messages` (fire-and-forget)
- "Give X a task to ..." → `POST /v1/tasks`, then poll `GET /v1/tasks/{id}`
  until `status == "done"` (action with a result)
- "What agents are online?" → `GET /v1/agents`
- "Did anyone message me?" → `GET /v1/messages?agent=claude-main`

## Calling convention

Use `curl -s` and pipe JSON through `python3 -m json.tool` for readable output.
**Do not run `a2a-client` interactively in a Bash tool call** — it's an
interactive REPL that will hang the tool call.

```bash
# register (idempotent — safe to call every session)
curl -s -X POST http://127.0.0.1:8765/v1/agents/register \
  -H 'Content-Type: application/json' \
  -d '{"id":"claude-main","name":"Claude Code","skills":["chat","code"]}'

# send a message
curl -s -X POST 'http://127.0.0.1:8765/v1/messages?from_agent=claude-main' \
  -H 'Content-Type: application/json' \
  -d '{"to_agent":"alice","content":{"text":"start working"}}'

# dispatch a task and wait for it
TID=$(curl -s -X POST 'http://127.0.0.1:8765/v1/tasks?from_agent=claude-main' \
  -H 'Content-Type: application/json' \
  -d '{"to_agent":"echo","type":"echo","input":{"msg":"ping"}}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["task_id"])')
while [ "$(curl -s http://127.0.0.1:8765/v1/tasks/$TID | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])')" != "done" ]; do sleep 0.5; done
curl -s http://127.0.0.1:8765/v1/tasks/$TID
```

A Python helper is also available in this project's venv:

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

- Don't pass messages via shared files, `/tmp` drops, or ad-hoc HTTP servers — use the hub.
- Don't open raw WebSockets from inside a tool call — the existing `a2a-client` CLI
  and `a2a.client.A2AClient` already handle the WS lifecycle.

## Setup status check

If a2a commands fail with `Connection refused`:

```bash
curl -sf http://127.0.0.1:8765/v1/agents >/dev/null && echo up || echo down
```

If `down`, start the hub (ask the user first if this is their machine):

```bash
nohup uv run -m a2a.server > ~/.a2a/hub.log 2>&1 &
```