"""End-to-end smoke test: spawn the FastAPI app on a random port and exercise the
core flows (register -> create task -> claim -> submit -> read back) plus WS p2p."""

from __future__ import annotations

import asyncio
import json
import socket
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn
import websockets

# force a temp DB BEFORE importing the server module
TMP_DB_DIR = tempfile.mkdtemp(prefix="a2a-test-")
TMP_DB = Path(TMP_DB_DIR) / "a2a.db"

import a2a.server as srv  # noqa: E402

srv.DB_PATH = TMP_DB  # override the module-level path

from a2a.server import app  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@asynccontextmanager
async def _running_server():
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    # wait for ready
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started, "server didn't start"
    base = f"http://127.0.0.1:{port}"
    ws_base = f"ws://127.0.0.1:{port}"
    try:
        yield base, ws_base
    finally:
        server.should_exit = True
        await task


@asynccontextmanager
async def _client(base: str, agent_id: str, name: str | None = None):
    c = httpx.AsyncClient(base_url=base, timeout=5)
    try:
        await c.post(
            "/v1/agents/register",
            json={"id": agent_id, "name": name or agent_id, "skills": ["echo"]},
        )
        yield c
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_register_and_list_agents():
    async with (
        _running_server() as (base, _ws),
        _client(base, "alpha") as _,
        _client(base, "beta", "Beta Bot") as _,
    ):
        r = await httpx.AsyncClient().get(f"{base}/v1/agents")
        ids = {a["id"] for a in r.json()}
        assert {"alpha", "beta"} <= ids


@pytest.mark.asyncio
async def test_task_lifecycle():
    async with (
        _running_server() as (base, _ws),
        _client(base, "alice") as alice,
        _client(base, "echo") as bob,
    ):
        # alice creates a task for echo
        r = await alice.post(
            "/v1/tasks?from_agent=alice",
            json={"to_agent": "echo", "type": "echo", "input": {"msg": "hello"}},
        )
        tid = r.json()["task_id"]

        # echo claims it
        r2 = await bob.post(f"/v1/tasks/{tid}/claim?agent_id=echo")
        assert r2.json()["status"] == "claimed"

        # echo submits result
        r3 = await bob.post(
            f"/v1/tasks/{tid}/result?agent_id=echo", json={"output": {"echo": {"msg": "hello"}}}
        )
        assert r3.json()["ok"] is True

        # alice reads it back
        r4 = await alice.get(f"/v1/tasks/{tid}")
        d = r4.json()
        assert d["status"] == "done"
        assert d["output"] == {"echo": {"msg": "hello"}}
        assert d["from_agent"] == "alice"


@pytest.mark.asyncio
async def test_p2p_message_via_ws():
    async with _running_server() as (base, ws_base):
        received: list[dict] = []
        ready = asyncio.Event()

        async def listen():
            async with websockets.connect(f"{ws_base}/ws/bob") as ws:
                ready.set()
                async for raw in ws:
                    received.append(json.loads(raw))
                    if len(received) >= 1:
                        return

        listener = asyncio.create_task(listen())
        await ready.wait()
        await asyncio.sleep(0.05)  # let bob's registration land

        async with _client(base, "alice") as alice:
            r = await alice.post(
                "/v1/messages?from_agent=alice", json={"to_agent": "bob", "content": {"text": "yo"}}
            )
            assert r.json()["delivered"] is True

        await asyncio.wait_for(listener, timeout=3)
        events = [m["event"] for m in received]
        assert "message" in events
        msg = next(m for m in received if m["event"] == "message")
        assert msg["from"] == "alice"
        assert msg["content"] == {"text": "yo"}
