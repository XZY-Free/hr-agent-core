# Orchestrator 部署边界

容器入口监听 `0.0.0.0:8000`。当前 dev Runtime 为 v33，公共 `hr-assistant` 入口 + 身份/Gaia 服务端装配，已通过完整 AgentKit 远端验收（WP01-WP07 授权边界内 PASS；当前镜像 `agentkit-platform-2101533667-cn-beijing.cr.volces.com/agentkit/hr-agent-vkba:ec927bc-wp07-final-confidence-7e97ace657c5`）。

完整 AgentKit 远端验收已通过（Codex 远端 `tests/agentkit` 用例验证，258 passed / 0 failed / 0 skipped）：

- Orchestrator 云 Runtime 已配置 `EMPLOYEE_IDENTITY_MAP_JSON` / `EMPLOYEE_REF_SECRET`（`TrustedIdentityResolver.from_env` 需要，服务端可信身份，非 Gaia 例外）；
- AgentCard 名称/URL 合规，测试已按 `HR_ACCEPTANCE_EXPECTED_IMAGES_JSON` 核对镜像（当前已发布版本见 [`deployment/README.md`](../../../deployment/README.md)）；
- 云已更新公共入口（`deployment/runtime_entry.py` 映射 `orchestrator → apps.orchestrator.public_a2a`），并修正 Leave `identity_unverified` 与 A2A 续接所有者守卫。

`GAIA_BACKEND=stub` 且干跑时 `gaia_server_config_from_env` 不再强制 Gaia 四项（默认 `gaia` 仍校验）；真实 Gaia/OAuth 未验证。WP01-WP07 在授权边界内 PASS，整体结论业务迁移非假实现整改：PASS（AgentKit 开发环境；Gaia 为授权 stub 边界）。

独立 Runtime 配置、A2A 客户端和云端资源按批次/审批建立；A2A Space / 注册 Agent 仅登记在 [`resource-inventory.yaml`](../../../deployment/resource-inventory.yaml)，当前状态待复核，不作实时已部署验证。凭据通过 Runtime secret / IAM 注入，不进 Git、日志或 Trace。云端写操作仍需既有授权，文档声明不构成部署权限。验收口径见 [`docs/agentkit-acceptance.md`](../../../docs/agentkit-acceptance.md)。
