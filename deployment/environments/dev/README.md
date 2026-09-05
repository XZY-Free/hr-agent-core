# 开发环境（dev）

dev 环境已部署到云 Runtime（Orchestrator v33 / Employee Data v11 / Consult v14，Ready、health 200）并已通过完整 AgentKit 远端验收（WP01-WP07 授权边界内 PASS）；公共 `hr-assistant` 入口、共享身份 map/ref、GaiaProvider 与 A2A 续接所有者守卫均已生效。当前已发布不可变镜像：Orchestrator `ec927bc-wp07-final-confidence-7e97ace657c5`、Employee Data `ec927bc-wp03-employee-balances-cdf7856146a1`、Consult `ec927bc-wp07-final-attendance-aff56a4e32c8`。

- 当前验收入口是 `tests/agentkit` 下对已部署 dev Runtime 的远端 HTTP 客户端用例（`pyproject` 默认 `testpaths=["tests/agentkit"]`），不装配本地业务 Agent、不自动读取本地配置文件。
- Gaia 保留 `GAIA_BACKEND=stub`、`EMPLOYEE_DATA_BACKEND=stub`、`GAIA_DRY_RUN=true`（用户授权边界），真实 Gaia 接入与 OAuth 缓存未验证、不计为已通过。Orchestrator 云 Runtime 已配置 `EMPLOYEE_IDENTITY_MAP_JSON` / `EMPLOYEE_REF_SECRET`（服务端可信身份，必需、非 Gaia 例外）。
- 全量 `tests/agentkit` 远端用例（共 258 项）已通过，WP01-WP07 在授权边界内 PASS，整体结论业务迁移非假实现整改：PASS（AgentKit 开发环境；Gaia 为授权 stub 边界）。缺远端用例不得用本地 fake 补齐。
- A2A Space / 注册 Agent 仅登记在 [`resource-inventory.yaml`](../../../deployment/resource-inventory.yaml)，当前状态待复核，不作实时已部署验证。
- 云端写操作仍需既有授权，文档声明不构成部署权限。详见 [`docs/agentkit-acceptance.md`](../../../docs/agentkit-acceptance.md)。
