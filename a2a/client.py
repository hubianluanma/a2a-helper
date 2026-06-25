"""a2a client: async library + interactive REPL.

Library usage
-------------
    from a2a.client import A2AClient
    c = A2AClient(base="http://127.0.0.1:8765", ws="ws://127.0.0.1:8765",
                  agent_id="claude-1", name="Claude",
                  description="main assistant", skills=["chat", "code"])
    await c.register()
    await c.connect_ws()          # background WS loop; events print to stdout
    await c.send_message("echo", {"text": "hi"})
    await c.create_task("echo", "echo", {"msg": "ping"})

CLI usage
---------
    python -m a2a.client --id claude-1 --name Claude
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import uuid
from typing import Any

import httpx
import websockets

# ANSI — keep them local so non-tty runs don't choke (we always flush, terminals handle it).
C_DIM = "\033[2m"
C_GRN = "\033[32m"
C_YEL = "\033[33m"
C_CYN = "\033[36m"
C_RST = "\033[0m"

PROMPT = f"{C_DIM}a2a>{C_RST} "


def log(tag: str, msg: str, color: str = C_DIM) -> None:
    print(f"{color}[{tag}]{C_RST} {msg}", flush=True)


# ---- core client ------------------------------------------------------------


class A2AClient:
    """Thin async client. Owns one httpx session + one ws connection per agent."""

    def __init__(
        self,
        base: str,
        ws_base: str,
        agent_id: str,
        name: str,
        description: str = "",
        skills: list[str] | None = None,
    ) -> None:
        self.base = base.rstrip("/")
        self.ws_base = ws_base.rstrip("/")
        self.agent_id = agent_id
        self.name = name
        self.card: dict[str, Any] = {
            "id": agent_id,
            "name": name,
            "description": description,
            "skills": skills or [],
        }
        self.http = httpx.AsyncClient(base_url=self.base, timeout=10)
        self.ws: websockets.WebSocketClientProtocol | None = None
        self._ws_task: asyncio.Task | None = None
        self._inbox: asyncio.Queue[dict] = asyncio.Queue()

    # ---- lifecycle ----

    async def register(self) -> None:
        r = await self.http.post("/v1/agents/register", json=self.card)
        r.raise_for_status()
        log("init", f"registered as {self.agent_id} ({self.name})", C_GRN)

    async def connect_ws(self) -> None:
        url = f"{self.ws_base}/ws/{self.agent_id}"
        self.ws = await websockets.connect(url)
        self._ws_task = asyncio.create_task(self._ws_loop())
        log("ws", f"connected to {url}", C_GRN)

    async def close(self) -> None:
        if self._ws_task:
            self._ws_task.cancel()
            with contextlib.suppress(BaseException):
                await self._ws_task
        if self.ws:
            await self.ws.close()
        await self.http.aclose()

    # ---- ws loop ----

    async def _ws_loop(self) -> None:
        assert self.ws is not None
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                # store for programmatic consumers
                await self._inbox.put(msg)
                ev = msg.get("event")
                if ev == "message":
                    print(
                        f"\n{C_CYN}<< msg from {msg['from']} {C_DIM}{msg['id']}{C_RST}\n"
                        f"  {msg['content']}"
                    )
                elif ev == "task.new":
                    print(f"\n{C_YEL}<< new task {msg['task_id']} type={msg['type']}{C_RST}")
                elif ev == "task.done":
                    print(f"\n{C_GRN}>> task done {msg['task_id']}: {msg['output']}{C_RST}")
                elif ev == "agent.online":
                    print(f"\n{C_GRN}>> online: {msg['agent_id']}{C_RST}")
                elif ev == "agent.offline":
                    print(f"\n{C_DIM}>> offline: {msg['agent_id']}{C_RST}")
                # ponytail: REPL jankiness if event lands mid-typing — accepted.
                # Upgrade path: wrap stdin in a tty-aware line-editor (prompt_toolkit).
        except websockets.exceptions.ConnectionClosed:
            log("ws", "disconnected", C_YEL)

    async def next_event(self, timeout: float | None = None) -> dict | None:
        try:
            return await asyncio.wait_for(self._inbox.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    # ---- ops ----

    async def send_message(self, to_agent: str, content: dict) -> dict:
        r = await self.http.post(
            "/v1/messages",
            params={"from_agent": self.agent_id},
            json={"to_agent": to_agent, "content": content},
        )
        r.raise_for_status()
        d = r.json()
        log("send", f"-> {to_agent}: id={d['id']} delivered={d['delivered']}", C_GRN)
        return d

    async def create_task(self, to_agent: str, type_: str, input_: dict) -> str:
        r = await self.http.post(
            "/v1/tasks",
            params={"from_agent": self.agent_id},
            json={"to_agent": to_agent, "type": type_, "input": input_},
        )
        r.raise_for_status()
        d = r.json()
        log("task", f"created {d['task_id']} -> {to_agent} type={type_}", C_GRN)
        return d["task_id"]

    async def get_task(self, task_id: str) -> dict:
        r = await self.http.get(f"/v1/tasks/{task_id}")
        r.raise_for_status()
        return r.json()

    async def claim(self) -> dict | None:
        """Claim oldest pending task assigned to me. None if empty."""
        r = await self.http.get("/v1/tasks", params={"agent": self.agent_id, "status": "pending"})
        r.raise_for_status()
        tasks = r.json()
        if not tasks:
            return None
        # oldest first
        tid = tasks[-1]["id"]
        try:
            r2 = await self.http.post(f"/v1/tasks/{tid}/claim", params={"agent_id": self.agent_id})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                return None  # someone else got it
            raise
        return r2.json()

    async def submit(self, task_id: str, output: dict) -> None:
        r = await self.http.post(
            f"/v1/tasks/{task_id}/result",
            params={"agent_id": self.agent_id},
            json={"output": output},
        )
        r.raise_for_status()
        log("submit", f"task {task_id} done", C_GRN)

    async def list_agents(self) -> list[dict]:
        r = await self.http.get("/v1/agents")
        r.raise_for_status()
        return r.json()


# ---- REPL -------------------------------------------------------------------

HELP = """\
commands:
  send <agent> <text>                  p2p message
  task <agent> <type> <json>           create task
  status <task_id>                     task detail
  claim                                claim next pending task for me
  submit <task_id> <json>              submit result for a task I own
  agents                               list registered agents (🟢 = online)
  help
  quit"""


async def _ainput(prompt: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))


async def repl(client: A2AClient) -> None:
    print(HELP)
    while True:
        try:
            line = (await _ainput(PROMPT)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        parts = line.split(maxsplit=2)
        cmd = parts[0]
        try:
            if cmd == "quit":
                return
            if cmd == "help":
                print(HELP)
            elif cmd == "agents":
                rows = await client.list_agents()
                for r in rows:
                    mark = "🟢" if r["ws_active"] else "⚪"
                    skills = ",".join(r["card"].get("skills", []))
                    print(f"  {mark} {r['id']:18s} {r['name']:20s} {skills}")
            elif cmd == "send" and len(parts) >= 3:
                await client.send_message(parts[1], {"text": parts[2]})
            elif cmd == "task" and len(parts) >= 3:
                rest = parts[2].split(maxsplit=1)
                if len(rest) < 2:
                    print("usage: task <agent> <type> <json>")
                    continue
                type_, js = rest
                try:
                    inp = json.loads(js)
                except json.JSONDecodeError as e:
                    print(f"invalid json: {e}")
                    continue
                await client.create_task(parts[1], type_, inp)
            elif cmd == "status" and len(parts) == 2:
                print(json.dumps(await client.get_task(parts[1]), indent=2, ensure_ascii=False))
            elif cmd == "claim":
                t = await client.claim()
                if t:
                    print(json.dumps(t, indent=2, ensure_ascii=False))
                else:
                    log("claim", "no pending tasks", C_YEL)
            elif cmd == "submit" and len(parts) >= 3:
                try:
                    out = json.loads(parts[2])
                except json.JSONDecodeError as e:
                    print(f"invalid json: {e}")
                    continue
                await client.submit(parts[1], out)
            else:
                print("unknown / incomplete command. type 'help'")
        except httpx.HTTPStatusError as e:
            print(f"http error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            print(f"error: {e}")


# ---- entry ------------------------------------------------------------------


async def _amain() -> None:
    p = argparse.ArgumentParser(prog="a2a-client")
    p.add_argument("--base", default=os.environ.get("A2A_BASE", "http://127.0.0.1:8765"))
    p.add_argument("--ws", default=os.environ.get("A2A_WS", "ws://127.0.0.1:8765"))
    p.add_argument("--id", default=None, help="agent id (default: random)")
    p.add_argument("--name", default=None)
    p.add_argument("--description", default="")
    p.add_argument("--skills", default="", help="comma-separated")
    args = p.parse_args()

    agent_id = args.id or f"agent-{uuid.uuid4().hex[:6]}"
    name = args.name or agent_id
    skills = [s.strip() for s in args.skills.split(",") if s.strip()]

    c = A2AClient(args.base, args.ws, agent_id, name, args.description, skills)
    await c.register()
    await c.connect_ws()
    try:
        await repl(c)
    finally:
        await c.close()


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_amain())


if __name__ == "__main__":
    main()
