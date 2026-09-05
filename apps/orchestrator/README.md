# Orchestrator 应用

`hr-orchestrator` 负责固定意图路由、进程内 Leave、页面跳转/JUMP、取消引导、人工入口和两个 A2A 消费者。它不直接查询 Knowledge 或员工本人数据。`local_leave` 是 Orchestrator **云进程**内的架构术语，不代表「电脑本地三服务」环境。

## 固定路由

| 优先级 | 意图 | 目标 |
|---|---|---|
| 1 | 请假申请、修改、请假多轮 | 进程内 Leave |
| 2 | 取消、撤回 | 进程内页面引导 |
| 3 | 本人余额、医疗期、工龄、年假折算 | Employee Data |
| 4 | 打开页面 | 进程内 `page_jump` |
| 5 | 制度、福利、系统操作、文档 | Consult |
| 6 | 人工服务 | 进程内人工入口 |
| 7 | 闲聊 | 进程内 Orchestrator |

远端目标由确定性规则选择，不由模型自由选择。本批不使用 A2A Space 语义发现。

## A2A 端点与公共入口

- 下游端点由 `HR_CONSULT_A2A_URL` / `HR_EMPLOYEE_DATA_A2A_URL` 服务端配置；未显式配置时 `agent.py` 保留 localhost 默认值，生产装配需显式设置。无 local transport 开关或静默回退。超时由 `HR_A2A_TIMEOUT_SECONDS` 控制，下游 Runtime 访问凭据为 `HR_CONSULT_RUNTIME_API_KEY` / `HR_EMPLOYEE_DATA_RUNTIME_API_KEY`。
- 公共入口监听 `HR_ASSISTANT_A2A_HOST=0.0.0.0` / `HR_ASSISTANT_A2A_PORT=8000`，访问模式 `HR_ASSISTANT_A2A_AUTH_MODE`。
- 本地源码 `deployment/runtime_entry.py` 已映射 `orchestrator → apps.orchestrator.public_a2a`（不再走 `agent.py`）；云端已更新为公共 `hr-assistant` 入口并通过完整 AgentKit 远端验收。

远端请求只发送 `request_id/user_id/session_id/caller_agent/locale/message/context_summary`。不发送完整 session、提示词、历史、employeeId 或任何密钥。A2A 失败返回目标专用安全话术，不走本地静默兜底。

## 公共执行上下文（身份与服务端配置）

公共入口通过 `apps/orchestrator/public_a2a/server.py::build_hr_context_builder` 装配身份与 Gaia：`TrustedIdentityResolver.from_env()` 需要 `EMPLOYEE_IDENTITY_MAP_JSON` / `EMPLOYEE_REF_SECRET`（服务端可信身份，必需、非 Gaia 例外）。`gaia_server_config_from_env()` 在显式 `GAIA_BACKEND=stub` 且 `GAIA_DRY_RUN=true` 时返回不带凭据的配置（默认 `gaia` 仍校验 Gaia 四项、未知 backend 拒绝）。云端已发布并通过完整 AgentKit 远端验收（WP01-WP07 授权边界内 PASS）；真实 Gaia/OAuth 未验证。详见 [`../../docs/agentkit-acceptance.md`](../../docs/agentkit-acceptance.md)。
