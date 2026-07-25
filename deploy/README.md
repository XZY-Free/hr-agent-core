# 部署与联调说明

## 本地起服务

```bash
# 1. 配置 .env（参考 .env.example）
#    MODEL_AGENT_NAME=doubao-seed-1.6-250615
#    MODEL_AGENT_API_KEY=<真实方舟模型 Key>   # 必填，否则 Agent 实例化时取 token 失败
#    GAIA_DRY_RUN=true                          # 一期保持干跑
#
# 2. 起服务（0.0.0.0:8000）
uv run python agent.py
```

## 本地联调验证（两个首验证项）

```bash
# 服务已起后，另开终端跑：
uv run python scripts/local_client.py --base-url http://localhost:8000 \
    --employee-id E001 --corp-id <盖亚租户ID> \
    --client-secret <盖亚应用密钥> --grant-type client_credentials
```

脚本会依次完成三项：
1. 创建会话时通过 body `state` 注入 4 个业务变量（employeeId / corp_id / client_secret / grant_type）
2. **验证①**：发「我还有几天年假？」→ 期望工具从 state 读到变量并发出盖亚请求（观察服务日志中 `openapi.gaiaworkforce.com` 请求 + Bearer JWT；SSE 回复应含余额数字）
3. **验证②**：发「打开打卡明细」→ 期望 SSE 最终文本含完整 `[[JUMP:punch-details]]`

### 备选方案：建会话传 state 不被支持时

若 AgentKit Runtime 不支持建会话时 body 传 `state`（验证①失败），在 `AgentkitAgentServerApp` 前加一层 FastAPI 中间件：从请求头 `X-Biz-Vars`（JSON）解析 4 个业务变量，写入 session state。

落地位置（待实施时创建）：
- `hr_agent/middleware/biz_vars.py`：FastAPI 中间件，解析 `X-Biz-Vars` 头 → 调 `session_service.update_session` 写入 state
- `agent.py`：`agent_server_app.app.add_middleware(BizVarsMiddleware)`

`local_client.py` 对应改造：`create_session` 不传 state，`run_sse` 请求头加 `X-Biz-Vars: {"employeeId":"...","corp_id":"...","client_secret":"...","grant_type":"..."}`。

---

## 当前阻塞

### Step 1 / Step 2：待 Key 试跑

- **阻塞原因**：当前开发环境无真实方舟模型 Key（`MODEL_AGENT_API_KEY`），`agent.py` 起服务时 Agent 实例化会触发 `get_ark_token()` 联网取 token，失败。
- **已就绪**：`scripts/local_client.py` 已实现完整三步验证逻辑；`agent.py` 入口已对齐官方 hello_world 形态。
- **解除条件**：在 `.env` 配置真实 `MODEL_AGENT_API_KEY` 后，按上述"本地起服务"+"本地联调验证"两节执行即可。

### Step 3：待环境

- **阻塞原因**：无火山引擎云账号，无法执行 `agentkit config` / `agentkit deploy`。
- **解除条件**：拿到云账号后，按 [AgentKit Runtime Quick Start](https://volcengine.github.io/agentkit-sdk-python) 执行部署，随后用 `local_client.py` 改 `--base-url` 为部署地址重跑两个验证项。

---

## AgentKit 部署（待环境）

具备云账号后执行（CLI 命令以官方 Runtime Quick Start 为准）：

```bash
# 1. 配置 AgentKit Runtime（云账号 AK/SK、应用名等）
agentkit config

# 2. 部署到 AgentKit Runtime
agentkit deploy

# 3. 部署后用 local_client.py 改 base_url 重跑两个验证项
uv run python scripts/local_client.py --base-url <部署地址> \
    --employee-id E001 --corp-id <盖亚租户ID> \
    --client-secret <盖亚应用密钥> --grant-type client_credentials
```
