[🇺🇸 English](README.md) · [🇨🇳 简体中文](README.zh.md)

# a2a-helper

[![CI](https://img.shields.io/github/actions/workflow/status/hubianluanma/a2a-helper/ci.yml?branch=main&label=CI)](https://github.com/hubianluanma/a2a-helper/actions)
[![PyPI](https://img.shields.io/pypi/v/a2a-helper)](https://pypi.org/project/a2a-helper/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/a2a-helper)](https://pypi.org/project/a2a-helper/)

一个轻量级的 agent-to-agent 中心。任何能跑 HTTP + WebSocket 的进程(Claude Code、Aider、Cursor、自研脚本)都可以注册成 agent,然后**实时收发点对点消息**或**异步派任务**。

灵感来自 [A2A Protocol](https://github.com/google/a2a-protocol)(`AgentCard` / `Task` / `Artifact` / `Message`),裁剪到约 300 行代码,单 SQLite 文件,零外部服务依赖。

> ⚠️ PyPI 上的包名是 `a2a-helper`,避免与 `google/a2a` 重名。代码里的 import 名仍为 `a2a`(与目录同名)。

## 安装

依赖通过 [uv](https://docs.astral.sh/uv/)(`uv ≥ 0.4`)管理,`pyproject.toml` 是单一来源,`uv.lock` 锁定精确版本。

从仓库 checkout 安装(开发模式,含 dev 依赖):

```bash
git clone https://github.com/hubianluanma/a2a-helper
cd a2a-helper
uv sync --all-extras --dev      # 在 .venv/ 创建虚拟环境并装好运行时 + dev 依赖
```

已发布版本(上传到 registry 后):

```bash
uvx a2a-server --port 8765      # 临时运行,类似 npx
# 或
uv tool install a2a-helper      # 装成全局命令
```

> 没装 uv?`pip install -e ".[dev]"` 也行 —— `pyproject.toml` 是符合标准的打包描述,不绑 uv。

## 快速开始

```bash
# 终端 1:启动 hub
a2a-server --port 8765

# 终端 2:启动 echo worker
a2a-echo --id echo

# 终端 3:启动交互客户端
a2a-client --id claude-1 --name Claude --skills chat,code
```

状态数据存放在 `~/.a2a/a2a.db`(SQLite,WAL 模式,并发读安全)。

默认 hub 绑定 `0.0.0.0:8765`,任何能访问本机 8765 端口的主机都可以连接 —— 适合跨机器协作场景。如果只想本机访问,传 `--host 127.0.0.1`。在共享网络上暴露前请先看 [`SECURITY.md`](SECURITY.md)。

## 功能

- **实时点对点消息**:目标 agent 在线时通过 WebSocket 推送;不在线时落到收件箱(`GET /v1/messages?agent=X`)。
- **异步任务**:派一个 `Task` 给另一个 agent;它 claim → 执行 → 提交 output。状态可查询,结果自动 push 回派发方。
- **在线状态**:连接时广播 `agent.online` / `agent.offline` 事件。
- **AgentCard**:每个 agent 注册 `id` + `name` + `skills[]`(`skills` 只是元数据,hub 不按 skill 路由)。

## 协议速查

```http
POST /v1/agents/register         {"id":"claude-1","name":"Claude","skills":["chat","code"]}
POST /v1/messages?from_agent=X   {"to_agent":"echo","content":{"text":"hi"}}
POST /v1/tasks?from_agent=X      {"to_agent":"echo","type":"echo","input":{"msg":"ping"}}
GET  /v1/tasks/{id}                                      # 返回 status + output
POST /v1/tasks/{id}/claim?agent_id=X                     # 拉取式认领
POST /v1/tasks/{id}/result?agent_id=X    {"output":{...}}
WS   /ws/{agent_id}                                      # 推送事件
```

完整参考:见 [`docs/CURSOR_USAGE.md`](docs/CURSOR_USAGE.md) — 以 Cursor 为示例讲解,但协议对所有 agent 通用。

## 10 行接入你的 agent

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

## 项目结构

```
a2a/                # 包(import 名 `a2a`)
  server.py         # FastAPI hub,SQLite,HTTP + WS
  client.py         # 异步 client 库 + REPL CLI
  echo_agent.py     # demo worker
tests/              # smoke 测试(随机端口启服务模式)
docs/               # 使用文档
```

## 开发

```bash
uv run ruff check .        # lint
uv run ruff format .       # 自动格式化
uv run pytest              # 3 个 smoke 测试必须通过
```

CI 在每个 PR 上跑同样三条命令。完整流程见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 让你的 AI 客户端认识 a2a

把下面两个文件之一拷到 **你的项目** 根目录,Cursor / Claude Code 就会自动知道 hub 怎么用,不用每次解释:

```bash
# 给 Cursor 用
cp examples/cursorrules /path/to/your/project/.cursorrules

# 给 Claude Code 用
cp examples/CLAUDE.md /path/to/your/project/CLAUDE.md
```

如果你的环境和默认不一样(端口、agent id 等),改文件顶部的几行。两份文件都列了所有端点、什么时候用消息 vs 任务、可直接粘贴的 `curl` 模板。

## 文档

- [`docs/CURSOR_USAGE.md`](docs/CURSOR_USAGE.md) — 以 Cursor 为示例的端到端用法
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — 开发流程、commit 规范
- [`CHANGELOG.md`](CHANGELOG.md) — 版本历史(Keep-a-Changelog 格式)
- [`SECURITY.md`](SECURITY.md) — 漏洞上报方式
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) — Contributor Covenant 2.1

## 状态与边界

Pre-1.0 版本,适用于单主机 + 可信 agent 环境;超出此场景请前置反向代理。Hub 本身**不带鉴权、不带 TLS、不带集群** — 这些是有意为之的省略,详见 [docs](docs/CURSOR_USAGE.md#9-它没做的事按需自加)。

## 协议

[MIT](LICENSE)。