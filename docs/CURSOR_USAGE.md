# a2a 使用说明(以 Cursor 为例)

把任意 AI 客户端(Cursor、Claude Code、Aider、自研脚本...)接入一个本地中心,让它们**互相收发消息、互相派任务**。本说明以 Cursor 为主示例,其他客户端走同一套协议。

---

## 1. 它是什么

```
┌─────────────┐        ┌────────────────┐        ┌─────────────┐
│  Cursor #1  │◄─WS──►│                │◄─WS───►│  Cursor #2  │
│  (CLI/插件) │   HTTP  │   a2a hub      │  HTTP   │  (CLI/插件) │
└─────────────┘        │  (本机进程)    │        └─────────────┘
                       │  ~/.a2a/a2a.db │
┌─────────────┐        │                │        ┌─────────────┐
│ Claude Code │◄─WS──►│  HTTP + WebSocket        │  Aider      │
└─────────────┘        └────────────────┘        └─────────────┘
```

- **点对点消息**:在线时实时推送(WebSocket),离线时落到收件箱(下次拉取)。
- **异步任务**:派一个 `Task` 给对方,对方 claim → 执行 → 提交 `output`,全程可追踪。
- **状态本地化**:数据存 `~/.a2a/a2a.db`(SQLite,WAL),不依赖任何外部服务。

---

## 2. 安装

依赖通过 [uv](https://docs.astral.sh/uv/)(`uv ≥ 0.4`)管理,`pyproject.toml` 是单一来源。

```bash
git clone <你的仓库> a2a && cd a2a
uv sync --all-extras --dev      # 创建 .venv/ 并装好运行时 + dev 依赖
```

需要 Python 3.10+。没装 uv 的:`pip install -e ".[dev]"` 仍然可用(`pyproject.toml` 兼容 pip)。

---

## 3. 启动 hub

```bash
# 默认监听 127.0.0.1:8765,DB 在 ~/.a2a/a2a.db
uv run -m a2a.server
```

换一个端口:

```bash
uv run -m a2a.server --port 9000
```

服务在前台跑就行;要后台用 `nohup ... &` 或 `tmux`。

---

## 4. 把 Cursor 接入 a2a

### 4.1 方式 A:用 `a2a.client` 作为 Cursor 的 adapter(推荐)

任何能跑 Python 的 Cursor 场景都能用这个办法。最常见两种:

#### 场景 1:Cursor IDE + 终端手动派活

在 Cursor 的集成终端里:

```bash
# 终端 1:启动 echo worker(代号 bob)
uv run -m a2a.echo_agent --id bob

# 终端 2:启动你的交互客户端(代号 alice)
uv run -m a2a.client --id alice --name "Alice (me)"
```

在 alice 的 REPL 里:

```text
a2a> agents
  🟢 alice          Alice (me)
  🟢 bob            Echo Bot          echo,upper

a2a> send bob 你好 bob
[send] -> bob: id=8f3a delivered=True

a2a> task bob echo {"msg": "ping from alice"}
[task] created 12ab -> bob type=echo

a2a> status 12ab
{
  "id": "12ab",
  "type": "echo",
  "input": {"msg": "ping from alice"},
  "output": {"echo": {"msg": "ping from alice"}},
  "status": "done",
  "to_agent": "bob",
  "from_agent": "alice"
}
```

#### 场景 2:Cursor CLI(headless 模式)作为 worker

`cursor-agent` 这类 headless 模式常用来跑长时间任务 — 给它套一层 a2a adapter,就能被其他 agent 派活。

```python
# my_cursor_worker.py
import asyncio, subprocess
from a2a.client import A2AClient

class CursorWorker(A2AClient):
    """把每个 task 喂给 cursor-agent CLI,把 stdout 当作 output 返回。"""

    async def handle(self, ttype, inp):
        prompt = inp.get("prompt", "")
        proc = await asyncio.create_subprocess_exec(
            "cursor-agent", "--print", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return {"reply": stdout.decode(), "exit": proc.returncode}


async def main():
    w = CursorWorker("http://127.0.0.1:8765", "ws://127.0.0.1:8765",
                     "cursor-1", "Cursor Headless", skills=["code", "review"])
    await w.register()
    await w.connect_ws()
    while True:
        t = await w.claim()
        if not t:
            await asyncio.sleep(0.5); continue
        out = await w.handle(t["type"], t["input"])
        await w.submit(t["id"], out)

asyncio.run(main())
```

跑起来后,任何其他 agent 都能派 `code`/`review` 类型的任务给 `cursor-1`:

```text
a2a> task cursor-1 code {"prompt": "把 foo.py 里的 print 改成 logging.info"}
```

### 4.2 方式 B:Cursor 里直接发 HTTP

如果你只想"手动戳一下 hub",不想要常驻进程,REPL 都省了 — 用 `curl` 就行:

```bash
# 注册自己
curl -X POST http://127.0.0.1:8765/v1/agents/register \
  -H 'Content-Type: application/json' \
  -d '{"id":"cur1","name":"Cursor 1","skills":["code"]}'

# 派一个 task 给 echo
curl -X POST 'http://127.0.0.1:8765/v1/tasks?from_agent=cur1' \
  -H 'Content-Type: application/json' \
  -d '{"to_agent":"bob","type":"echo","input":{"msg":"hi"}}'
# → {"task_id":"...","status":"pending"}

# 查结果
curl http://127.0.0.1:8765/v1/tasks/<task_id>

# 列在线 agent
curl http://127.0.0.1:8765/v1/agents
```

适合在 Cursor 的快捷命令 / 脚本片段里调一下,不引入 Python 依赖。

---

## 5. 多 Cursor 之间的常用操作

### 5.1 实时聊天

```text
a2a> send cursor-2 帮我看看 src/auth.py 的逻辑
[send] -> cursor-2: id=xx delivered=True
<< msg from cursor-2 ...
  {"text": "看了下,建议..."}
```

### 5.2 派任务并等结果

```text
a2a> task cursor-2 review {"files": ["src/auth.py","src/user.py"]}
[task] created ... -> cursor-2 type=review

a2a> status <task_id>
... 等几秒后再查 ...
{
  "status": "done",
  "output": {"comments": [...]}
}
```

### 5.3 让一个 Cursor 把活转交给另一个

```python
# 在 CursorWorker.handle 里
async def handle(self, ttype, inp):
    if ttype == "delegate":
        # 收到"让 cursor-2 干这个 prompt"的请求
        sub_id = await self.create_task("cursor-2", inp["type"], inp["input"])
        # 阻塞等结果(简化版:轮询)
        while True:
            sub = await self.get_task(sub_id)
            if sub["status"] == "done":
                return sub["output"]
            await asyncio.sleep(0.5)
```

### 5.4 广播/群发

当前没有原生的广播事件,但可以拉所有在线 agent,然后对每个 `send` 一次:

```python
agents = await client.list_agents()
for a in agents:
    if a["id"] != client.agent_id and a["ws_active"]:
        await client.send_message(a["id"], {"text": "群里通知一下"})
```

---

## 6. 协议速查

### HTTP

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET`  | `/v1/agents` | 列注册过的 agent |
| `POST` | `/v1/agents/register` | 注册/更新自己的 AgentCard |
| `POST` | `/v1/messages?from_agent=X` | 给 Y 发 p2p 消息(JSON `content`) |
| `GET`  | `/v1/messages?agent=X&limit=N` | 拉自己的收件箱 |
| `POST` | `/v1/tasks?from_agent=X` | 派任务给 Y(`type` + `input`) |
| `GET`  | `/v1/tasks?agent=X&status=Y` | 列表(`pending`/`claimed`/`done`/`failed`) |
| `GET`  | `/v1/tasks/{id}` | 任务详情 |
| `POST` | `/v1/tasks/{id}/claim?agent_id=X` | 认领任务 |
| `POST` | `/v1/tasks/{id}/result?agent_id=X` | 提交 `output` |

### WebSocket

```text
WS /ws/<agent_id>
  ← 服务端推送:{event: "message"|"task.new"|"task.done"|"agent.online"|"agent.offline", ...}
  → 客户端可发:{event: "ping"}
```

### AgentCard

```json
{
  "id": "cur1",
  "name": "Cursor 1",
  "description": "主 IDE 实例",
  "skills": ["code", "review", "translate"]
}
```

`skills` 只是个标签,目前不做匹配路由,只是方便其他 agent 在 `agents` 列表里看出谁会啥。

---

## 7. 常见工作流

### 7.1 主 IDE 把琐碎活交给 headless 实例

主 IDE 想跑一堆 lint / 格式化,但不想阻塞 UI?把它派给 headless:

```text
a2a> task cursor-cli lint {"files": ["a.py","b.py","c.py"]}
```

headless 那边 claim → 跑工具 → 提交结果。

### 7.2 两个 IDE 联调

IDE A 在调前端,IDE B 在调后端,两边需要确认接口字段名:

```text
# A
a2a> send cursor-b /api/user 返回字段是 userId 还是 id?

# B(看到推送)
<< msg from cursor-a ...
  {"text": "/api/user 返回字段是 userId 还是 id?"}
```

### 7.3 Cursor 当路由器:把外部 webhook 转给对应 agent

```python
# webhook_bridge.py — 简单的 a2a 适配
from a2a.client import A2AClient
# 收到 GitHub PR webhook → 转给 review-capable agent
```

---

## 8. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `Connection refused` | hub 没起 | 先跑 `uv run -m a2a.server` |
| `delivered: False` | 目标 agent 没连 WS | 目标需要 `connect_ws()`;消息已落 DB,下次拉收件箱可拿到 |
| `agent X not registered` | 派任务前没 register | 让对方先 `register`(任意时间) |
| 收不到推送但能 `claim` 到任务 | WS 心跳断了 | 看 hub 日志,通常重启 client 即恢复 |
| 任务一直 `pending` | 没人 claim | 确认目标 agent 在跑、id 一致、`skills` 不影响路由 |

---

## 9. 它**没**做的事(按需自加)

- ❌ 鉴权 — 当前任何人都能注册任意 id。本机单人/可信网络够用,公网请前置反向代理加认证。
- ❌ TLS — 当前是明文 HTTP/WS。出本机请套 nginx/caddy。
- ❌ 消息加密 / 端到端签名 — 不存敏感数据就没事。
- ❌ 集群 — 单进程 hub,水平扩展需要换 Postgres + 多实例 + 共享 WS 状态。
- ❌ 任务依赖图 / DAG — 当前每个任务独立,需要编排层在外面做。