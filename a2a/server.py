"""a2a server: HTTP + WebSocket, SQLite-backed.

Endpoints
---------
GET    /v1/agents                       list registered agents
POST   /v1/agents/register              upsert an AgentCard
POST   /v1/messages?from_agent=X        send a p2p message to another agent
GET    /v1/messages?agent=X&limit=N     inbox dump (last N)
POST   /v1/tasks                        create a task for a target agent
GET    /v1/tasks?agent=X&status=Y       list tasks (filter)
GET    /v1/tasks/{id}                   task detail
POST   /v1/tasks/{id}/claim?agent_id=X  claim a pending task
POST   /v1/tasks/{id}/result?agent_id=X submit result for a task I own
WS     /ws/{agent_id}                   live channel: messages + task.new events

Run:    uv run -m a2a.server           (default 0.0.0.0:8765 — see SECURITY.md)
        uv run -m a2a.server --host 127.0.0.1    # loopback only
        # or, after `uv tool install a2a-helper`:  a2a-server --port 8765
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

DB_PATH = Path.home() / ".a2a" / "a2a.db"

# ---- storage ----------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    card        TEXT,
    ws_active   INTEGER DEFAULT 0,
    last_seen   INTEGER
);
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    type        TEXT,
    input       TEXT,
    output      TEXT,
    status      TEXT,
    from_agent  TEXT,
    to_agent    TEXT,
    created_at  INTEGER,
    updated_at  INTEGER
);
CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    from_agent  TEXT,
    to_agent    TEXT,
    content     TEXT,
    created_at  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tasks_to_status ON tasks(to_agent, status);
CREATE INDEX IF NOT EXISTS idx_msg_to ON messages(to_agent, created_at);
"""


def init_db() -> None:
    with _connect() as c:
        c.executescript(SCHEMA)


# ---- models -----------------------------------------------------------------


class AgentCard(BaseModel):
    id: str
    name: str
    description: str = ""
    skills: list[str] = Field(default_factory=list)


class CreateTask(BaseModel):
    type: str
    input: dict[str, Any]
    to_agent: str


class SubmitResult(BaseModel):
    output: dict[str, Any]


class SendMessage(BaseModel):
    to_agent: str
    content: dict[str, Any]


# ---- live socket registry ---------------------------------------------------


class Registry:
    """In-process map of currently-connected WS clients."""

    def __init__(self) -> None:
        self._sockets: dict[str, WebSocket] = {}

    def add(self, agent_id: str, ws: WebSocket) -> None:
        self._sockets[agent_id] = ws

    def remove(self, agent_id: str) -> None:
        self._sockets.pop(agent_id, None)

    def get(self, agent_id: str) -> WebSocket | None:
        return self._sockets.get(agent_id)

    def online_ids(self) -> list[str]:
        return list(self._sockets.keys())


REG = Registry()
_LOOP: asyncio.AbstractEventLoop | None = None

# ---- app --------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    global _LOOP
    _LOOP = asyncio.get_running_loop()
    yield


app = FastAPI(title="a2a", lifespan=lifespan)


def _schedule_push(agent_id: str, payload: dict) -> bool:
    """Schedule a WS push from a sync (threadpool) handler. Returns optimistic flag."""
    if _LOOP is None:
        return False
    try:
        asyncio.run_coroutine_threadsafe(_push(agent_id, payload), _LOOP)
        return True
    except Exception:
        return False


# ---- helpers ----------------------------------------------------------------


def _now() -> int:
    return int(time.time())


def _agent_row_to_dict(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "card": json.loads(r["card"]) if r["card"] else {},
        "ws_active": bool(r["ws_active"]),
        "last_seen": r["last_seen"],
    }


def _task_row_to_dict(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "type": r["type"],
        "input": json.loads(r["input"]) if r["input"] else {},
        "output": json.loads(r["output"]) if r["output"] else None,
        "status": r["status"],
        "from_agent": r["from_agent"],
        "to_agent": r["to_agent"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


async def _push(agent_id: str, payload: dict) -> bool:
    """Send a JSON event to a live socket, if any. Returns delivered flag."""
    ws = REG.get(agent_id)
    if not ws:
        return False
    try:
        await ws.send_json(payload)
        return True
    except Exception:
        REG.remove(agent_id)
        return False


async def _broadcast(payload: dict, exclude: str | None = None) -> None:
    for aid in list(REG.online_ids()):
        if aid == exclude:
            continue
        await _push(aid, payload)


# ---- routes: agents ---------------------------------------------------------


@app.get("/v1/agents")
def list_agents() -> list[dict]:
    with _connect() as c:
        rows = c.execute(
            "SELECT id, name, card, ws_active, last_seen FROM agents ORDER BY last_seen DESC"
        ).fetchall()
    return [_agent_row_to_dict(r) for r in rows]


@app.post("/v1/agents/register")
def register_agent(card: AgentCard) -> dict:
    with _connect() as c:
        c.execute(
            "INSERT INTO agents(id, name, card, last_seen) VALUES(?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "  name=excluded.name, card=excluded.card, last_seen=excluded.last_seen",
            (card.id, card.name, card.model_dump_json(), _now()),
        )
    return {"ok": True, "id": card.id}


# ---- routes: messages (p2p) -------------------------------------------------


@app.post("/v1/messages")
def send_message(req: SendMessage, from_agent: str = Query(...)) -> dict:
    msg_id = uuid.uuid4().hex[:12]
    with _connect() as c:
        # validate both sides exist (light)
        c.execute("SELECT 1 FROM agents WHERE id IN (?, ?)", (from_agent, req.to_agent))
        c.execute(
            "INSERT INTO messages(id, from_agent, to_agent, content, created_at) VALUES(?,?,?,?,?)",
            (msg_id, from_agent, req.to_agent, json.dumps(req.content), _now()),
        )
    delivered = _schedule_push(
        req.to_agent,
        {
            "event": "message",
            "id": msg_id,
            "from": from_agent,
            "content": req.content,
        },
    )
    return {"id": msg_id, "delivered": delivered, "stored": True}


@app.get("/v1/messages")
def inbox(agent: str, limit: int = 50) -> list[dict]:
    with _connect() as c:
        rows = c.execute(
            "SELECT id, from_agent, content, created_at FROM messages "
            "WHERE to_agent=? ORDER BY created_at DESC LIMIT ?",
            (agent, limit),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "from": r["from_agent"],
            "content": json.loads(r["content"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---- routes: tasks ----------------------------------------------------------


@app.post("/v1/tasks")
def create_task(req: CreateTask, from_agent: str | None = Query(default=None)) -> dict:
    with _connect() as c:
        if not c.execute("SELECT 1 FROM agents WHERE id=?", (req.to_agent,)).fetchone():
            raise HTTPException(404, f"agent {req.to_agent} not registered")
        task_id = uuid.uuid4().hex[:12]
        c.execute(
            "INSERT INTO tasks(id, type, input, status, from_agent, to_agent, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                task_id,
                req.type,
                json.dumps(req.input),
                "pending",
                from_agent,
                req.to_agent,
                _now(),
                _now(),
            ),
        )
    _schedule_push(
        req.to_agent,
        {
            "event": "task.new",
            "task_id": task_id,
            "type": req.type,
        },
    )
    return {"task_id": task_id, "status": "pending"}


@app.get("/v1/tasks")
def list_tasks(
    agent: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    q = "SELECT * FROM tasks WHERE 1=1"
    args: list[Any] = []
    if agent:
        q += " AND to_agent=?"
        args.append(agent)
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with _connect() as c:
        rows = c.execute(q, args).fetchall()
    return [_task_row_to_dict(r) for r in rows]


@app.get("/v1/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    with _connect() as c:
        r = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not r:
        raise HTTPException(404, "no such task")
    return _task_row_to_dict(r)


@app.post("/v1/tasks/{task_id}/claim")
def claim_task(task_id: str, agent_id: str = Query(...)) -> dict:
    with _connect() as c:
        cur = c.execute(
            "UPDATE tasks SET status='claimed', updated_at=? "
            "WHERE id=? AND status='pending' AND to_agent=?",
            (_now(), task_id, agent_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "task not claimable (not pending or not yours)")
        r = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _task_row_to_dict(r)


@app.post("/v1/tasks/{task_id}/result")
def submit_result(
    task_id: str,
    req: SubmitResult,
    agent_id: str = Query(...),
) -> dict:
    with _connect() as c:
        cur = c.execute(
            "UPDATE tasks SET status='done', output=?, updated_at=? WHERE id=? AND to_agent=?",
            (json.dumps(req.output), _now(), task_id, agent_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "task not found or wrong agent")
    # notify requester if known
    with _connect() as c:
        row = c.execute("SELECT from_agent FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row and row["from_agent"]:
        _schedule_push(
            row["from_agent"],
            {
                "event": "task.done",
                "task_id": task_id,
                "output": req.output,
            },
        )
    return {"ok": True}


# ---- websocket --------------------------------------------------------------


@app.websocket("/ws/{agent_id}")
async def ws_endpoint(ws: WebSocket, agent_id: str) -> None:
    await ws.accept()
    REG.add(agent_id, ws)
    with _connect() as c:
        c.execute("UPDATE agents SET ws_active=1, last_seen=? WHERE id=?", (_now(), agent_id))
    await _broadcast({"event": "agent.online", "agent_id": agent_id}, exclude=agent_id)
    try:
        while True:
            data = await ws.receive_json()
            with _connect() as c:
                c.execute("UPDATE agents SET last_seen=? WHERE id=?", (_now(), agent_id))
            ev = data.get("event")
            if ev == "ping":
                await ws.send_json({"event": "pong", "t": _now()})
            # future: presence, typing, etc.
    except WebSocketDisconnect:
        pass
    finally:
        REG.remove(agent_id)
        with _connect() as c:
            c.execute("UPDATE agents SET ws_active=0, last_seen=? WHERE id=?", (_now(), agent_id))
        await _broadcast({"event": "agent.offline", "agent_id": agent_id})


# ---- main -------------------------------------------------------------------


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address. Default 0.0.0.0 (all interfaces, any host that "
        "can reach this machine on the port can connect). Pass 127.0.0.1 "
        "to restrict to loopback.",
    )
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    import uvicorn

    uvicorn.run("a2a.server:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
