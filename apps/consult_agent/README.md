# Consult Agent应用

`hr_consult_agent`负责制度政策、考勤、薪酬福利、人事系统操作和人力文档问答。它只装配`kb_search`与`parse_document`，不查询员工本人数据、不办理请假，也不依赖Orchestrator或Gaia工具。

## 两种本地入口

- 根`agent.py`把同一个构建结果作为本地`sub_agent`使用，保持单Runtime回归入口。
- `python -m apps.consult_agent`在`127.0.0.1:8101`启动官方A2A JSON-RPC/SSE服务。

独立服务地址：

| 接口 | 地址 |
|---|---|
| 健康检查 | `http://127.0.0.1:8101/health` |
| AgentCard | `http://127.0.0.1:8101/.well-known/agent-card.json` |
| JSON-RPC与SSE | `http://127.0.0.1:8101/` |

## 独立配置

必须配置模型Key、`KB_BACKEND=agentkit`、四个collection映射和Viking服务端AK/SK。endpoint、region、scheme、project及STS token按实际资源配置。独立入口不要求`employeeId`、`corp_id`、`client_secret`、`grant_type`或Gaia endpoint；缺少必要配置时启动失败。

去密变量清单见仓库根[`.env.example`](../../.env.example)。本地服务仅监听loopback，当前不额外实现应用层API Key；开发Runtime的A2A鉴权留待获批云端部署时使用平台能力验证。

`policy`、`handbook`、`salary`、`childcare`四个scope的collection映射、`all`聚合语义、`top_k=5`和Viking官方SDK适配保持不变。
