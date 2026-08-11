# Consult Agent应用

`hr_consult_agent`负责人力制度、政策、考勤、薪酬福利、系统操作和文档问答。它只装配`kb_search`与`parse_document`，不查询员工本人数据、不办理请假，也不依赖Orchestrator或Gaia。

## 本地入口

`python -m apps.consult_agent`在`127.0.0.1:8101`启动官方A2A JSONRPC/SSE服务。Consult不再被生产Orchestrator作为本地子Agent装配。

| 接口 | 地址 |
|---|---|
| 健康检查 | `http://127.0.0.1:8101/health` |
| AgentCard | `http://127.0.0.1:8101/.well-known/agent-card.json` |
| JSONRPC/SSE | `http://127.0.0.1:8101/` |

独立服务需要模型Key、`KB_BACKEND=agentkit`、四个collection映射和Viking服务端AK/SK；endpoint、region、scheme、project和STS token按资源配置。它不接收`employeeId`、Gaia配置或根session state。

`policy`、`handbook`、`salary`、`childcare`映射、`all`语义、`top_k=5`、QPS重试和Viking官方公开SDK保持不变。Knowledge响应保留真实`content/source/score`；A2A Artifact只带受控来源和分数，不带切片正文。
