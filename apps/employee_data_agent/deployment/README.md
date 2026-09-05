# Employee Data 部署边界

Employee Data 独立 A2A 服务部署在云 Runtime（当前版本 v11，`EMPLOYEE_DATA_BACKEND=stub`，有服务端可信身份 map/ref，已通过完整 AgentKit 远端验收；当前镜像 `agentkit-platform-2101533667-cn-beijing.cr.volces.com/agentkit/hr-agent-vkba:ec927bc-wp03-employee-balances-cdf7856146a1`）。未生成独立部署配置。

运行时凭据（模型 Key、`EMPLOYEE_IDENTITY_MAP_JSON`、`EMPLOYEE_REF_SECRET`、Gaia 服务端配置）通过 Runtime secret / IAM 注入，不进 Git、日志或 Trace。真实 Gaia 连通性与 OAuth 缓存证据**尚未验证**、不计为已通过；当前授权边界为 `EMPLOYEE_DATA_BACKEND=stub`（本 Agent 的 stub provider 不读取 Gaia 四项；Orchestrator 公共 builder 在 `stub` 干跑时也不再强制 Gaia 四项——云端已生效）。A2A Space / 注册 Agent 仅登记在 [`resource-inventory.yaml`](../../../deployment/resource-inventory.yaml)，当前状态待复核。开发 Runtime、身份和 A2A 提供者信息在批次 4 完成后按审批配置；云端写操作仍需既有授权。验收口径见 [`docs/agentkit-acceptance.md`](../../../docs/agentkit-acceptance.md)。
