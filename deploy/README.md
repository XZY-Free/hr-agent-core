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

### Step 1 / Step 2：✅ 已验证（2026-07-30）

- 模型 Key 已配 `.env`，服务可正常起（三个 Agent 实例化成功，`thinking: disabled` 已生效）。
- **验证①（state 传参管道）**：通过——工具能从 session state 读到 4 个业务变量并尝试发盖亚请求
  （本地用 dummy 凭据，JWT 获取如预期失败，证明变量已传到工具层）。
  **顺带抓到一个真缺陷**：查询工具返回 `gaia_error` 时模型竟回"已为您转接人工客服"
  （假转接，实际没有转接动作）——根因是 prompt 没写工具失败时的降级行为，模型就近抓了
  handoff 当逃生出口。已在 MAIN prompt 第 3 条补规则：失败如实转述"请稍后重试"，
  不转人工、不出现技术词汇。修复后复测回"查询失败，请稍后重试。"
- **验证②（JUMP 透传）**：通过——SSE 最终文本含完整 `[[JUMP:punch-details]]`。
- **待真凭据重验**：拿到盖亚真实 `corp_id` / `client_secret` 后重跑 `local_client.py`，
  验证①应返回真实余额数字而非"查询失败"。

### Step 3：待环境

- **阻塞原因**：无火山引擎云账号，无法执行 `agentkit config` / `agentkit deploy`。
  注意 `.env` 里已有知识库用的 `VOLCENGINE_ACCESS_KEY/SECRET_KEY`——若该账号开通了
  AgentKit Runtime 权限，部署即无外部阻塞，可先确认这一点。
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
