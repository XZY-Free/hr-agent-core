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

### Step 3：✅ 已部署（2026-07-30）

**Endpoint：`https://s6ifts5crqam93ibb6o7p.apigateway-cn-beijing.volceapi.com`**
（key_auth：`Authorization: Bearer <ApiKey>`，key 值从
`agentkit runtime get -r r-yerqme2fb4gumvo41qdj --output json` 的
`AuthorizerConfiguration.KeyAuth.ApiKey` 取）

线上验证结果（local_client.py --base-url <endpoint> --apikey <key>）：

| 项 | 结果 |
|---|---|
| 会话注入 4 个业务变量（state 传参） | ✅ |
| 验证① 查询降级行为（dummy 盖亚凭据 → "查询失败，请稍后重试"） | ✅ |
| 验证② SSE 含完整 `[[JUMP:punch-details]]` | ✅ |
| 真 Viking 知识库检索（`agentkit invoke "迟到扣款制度是什么样的"` 答出分段计费规则） | ✅ |

自动创建的云资源（均在计费）：TOS bucket `agentkit-platform-2101533667`、
CR 仓库 `agentkit/hr-agent-vkba`、Pipeline `hr-agent-nbgplh40`、
Runtime `r-yerqme2fb4gumvo41qdj`（2C4G，MinInstance 1 / Max 10）、API Key `API-KEY-u17dymup`。
**不用时记得 `agentkit destroy` 释放。**

---

## AgentKit 部署 / 更新

首次部署已完成（`agentkit config` 生成 `agentkit.yaml` + `agentkit launch`）。
`agentkit.yaml` 含密钥已 gitignore；`requirements.txt` 由
`uv export --no-dev --no-hashes -o requirements.txt` 再生成，也不入库。

**改代码后重新部署**（在 hr-agent 目录，先导出 AK/SK）：

```bash
set -a && . ./.env && set +a
uv export --no-dev --no-hashes -o requirements.txt   # 依赖有变化时
uv run agentkit launch                                # 重新构建+部署，endpoint 不变
```

**改运行时环境变量**：编辑 `agentkit.yaml` 的 `common.runtime_envs` 后重新 `launch`。

**线上重验**：

```bash
# 先取 API Key（见上），然后
uv run python scripts/local_client.py \
    --base-url https://s6ifts5crqam93ibb6o7p.apigateway-cn-beijing.volceapi.com \
    --apikey <ApiKey> --employee-id E001 \
    --corp-id <盖亚租户ID> --client-secret <盖亚应用密钥> --grant-type client_credentials
```
