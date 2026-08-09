# Consult部署边界

当前只提供本地独立入口，不包含真实`agentkit.yaml`，也未创建云资源。未来开发资源名称固定为：

| 资源 | 名称 | 地域 | 当前状态 |
|---|---|---|---|
| Runtime | `hr-consult-agent-dev` | `cn-beijing` | planned |
| A2A Agent | `hr-consult-agent` | `cn-beijing` | planned |
| A2A Space | `hr-agents-dev` | `cn-beijing` | planned |

运行时凭据必须通过Runtime secret或IAM/STS注入，不得写入仓库、AgentCard、A2A消息、日志或Trace。任何云端写操作必须等批次6部署清单获用户明确批准后执行。
