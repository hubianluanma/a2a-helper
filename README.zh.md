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

把 skill 拷到 **你的项目** 根目录。Claude Code 和 Cursor 都会读 `.claude/skills/`,一份拷贝两个客户端通用:

```bash
mkdir -p /path/to/your/project/.claude/skills
cp -r skills/a2a-helper /path/to/your/project/.claude/skills/
```

Cursor 单独的项目也可以用 `.cursor/skills/`(同样布局、同样的 `SKILL.md`)。格式遵循开放的 [Agent Skills](https://agentskills.io) 标准。

拷过去之后,在 Claude Code 里可以直接 `/a2a-helper` 显式激活,或在对话里提到 "a2a" / "agent hub" / "给某个 agent 发消息" 等关键词时自动激活。Cursor 同样会自动识别。

### 配置 `SKILL.md` 顶部的 4 个变量

打开拷过去的 `SKILL.md`,编辑**顶部**的 Configuration 块。下面的所有命令都引用这几个变量,改一次全部生效:

```bash
A2A_HOME=/path/to/your/a2a-helper/clone    # 仅在启动 hub / 拉起本地 worker 时需要
HUB_HTTP=http://your-hub-host:8765         # hub 的可达地址
HUB_WS=ws://your-hub-host:8765
AGENT_ID=your-unique-id-here               # 本次会话的 id
```

要哪些变量取决于你要干什么:

| 你想...                                            | 需要                              |
|----------------------------------------------------|-----------------------------------|
| 发送消息 / 派任务 / 列表 / claim / submit(纯 HTTP)| `HUB_HTTP`、`AGENT_ID`            |
| 在本机启动 hub                                     | + `A2A_HOME`                      |
| 在本机起 worker(如 `a2a.echo_agent`)              | + `A2A_HOME`                      |
| 接收 WS 实时推送                                   | `HUB_WS`                          |

所以**只跟远程 hub 通信**的话,根本不需要 `A2A_HOME`。如果 `a2a-server` / `a2a-client` 已经在 PATH 里(比如 `uv tool install a2a-helper` 之后),这些命令也能跳过 `A2A_HOME`。

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