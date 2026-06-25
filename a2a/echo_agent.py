"""Echo demo agent: claims tasks of type=echo and submits the input as output.

Usage:
    python -m a2a.echo_agent            # registers as 'echo'
    python -m a2a.echo_agent --id bob   # registers as 'bob'
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os

from a2a.client import C_GRN, C_YEL, A2AClient, log


async def _serve(client: A2AClient) -> None:
    """Poll loop: claim a task if any, otherwise sleep. Run forever."""
    while True:
        try:
            t = await client.claim()
            if t is None:
                await asyncio.sleep(0.5)
                continue
            ttype = t["type"]
            log("echo", f"got task {t['id']} type={ttype} input={t['input']}", C_YEL)
            if ttype == "echo":
                await client.submit(t["id"], {"echo": t["input"]})
            elif ttype == "upper":
                text = t["input"].get("text", "")
                await client.submit(t["id"], {"text": text.upper()})
            else:
                await client.submit(t["id"], {"error": f"unknown type {ttype}"})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log("echo", f"loop error: {e}", C_YEL)
            await asyncio.sleep(1)


async def _amain() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default=os.environ.get("A2A_BASE", "http://127.0.0.1:8765"))
    p.add_argument("--ws", default=os.environ.get("A2A_WS", "ws://127.0.0.1:8765"))
    p.add_argument("--id", default="echo")
    p.add_argument("--name", default="Echo Bot")
    args = p.parse_args()

    c = A2AClient(
        args.base,
        args.ws,
        args.id,
        args.name,
        description="echoes input back as output",
        skills=["echo", "upper"],
    )
    await c.register()
    await c.connect_ws()
    log("echo", "running, claim type=echo or type=upper", C_GRN)
    try:
        await _serve(c)
    finally:
        await c.close()


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_amain())


if __name__ == "__main__":
    main()
