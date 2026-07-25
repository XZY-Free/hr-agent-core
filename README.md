# 人力 AI 智能体（一期）

考勤请假智能体，基于 veADK + AgentKit，迁移自 FastGPT 工作流。

## 开发

```bash
uv sync
uv run pytest -v          # 规则/工具层单测（默认跳过 eval）
uv run pytest -m eval -v   # 对话评测（需 .env 配置方舟模型 Key）
uv run python agent.py     # 本地 8000 端口起 AgentKit 服务
```

## 环境变量（.env）

- `MODEL_AGENT_NAME`：模型名（默认 `doubao-seed-1.6-250615`）
- `GAIA_DRY_RUN`：`true` 时 submit_leave 仅干跑（一期默认）

业务变量（`employeeId` / `corp_id` / `client_secret` / `grant_type`）由调用方按会话注入 ADK `session.state`，工具从 state 读取，不进 prompt。
