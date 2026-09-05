# Consult 部署边界

Consult 独立 A2A 服务部署在云 Runtime（当前版本 v14，`KB_BACKEND=agentkit`，四个 collection 已配置；当前镜像 `agentkit-platform-2101533667-cn-beijing.cr.volces.com/agentkit/hr-agent-vkba:ec927bc-wp07-final-attendance-aff56a4e32c8`）。本文件不包含真实 `agentkit.yaml`。资源登记见 [`deployment/resource-inventory.yaml`](../../../deployment/resource-inventory.yaml)。未来开发资源名称固定为：

| 资源 | 名称 | 地域 | 当前状态 |
|---|---|---|---|
| Runtime | `hr-consult-agent-dev` | `cn-beijing` | 已部署（v14，通过完整 AgentKit 远端验收） |
| A2A Agent | `hr-consult-agent` | `cn-beijing` | 资源清单登记，当前状态待复核 |
| A2A Space | `hr-agents-dev` | `cn-beijing` | 资源清单登记，当前状态待复核 |

运行时凭据必须通过 Runtime secret 或 IAM/STS 注入，不得写入仓库、AgentCard、A2A 消息、日志或 Trace。任何云端写操作必须等对应批次/审批获用户明确批准后执行；文档声明不构成部署授权。当前验收入口是 `tests/agentkit` 下对已部署 Consult Runtime 的远端 HTTP 客户端用例（`KB_BACKEND=agentkit` 为服务端配置，测试不能注入 session state 伪造业务事实）。详见 [`docs/agentkit-acceptance.md`](../../../docs/agentkit-acceptance.md)。
