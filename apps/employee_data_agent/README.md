# Employee Data Agent 应用

`hr_employee_data_agent` 是独立只读 Agent，只查询当前员工本人的假期余额、医疗期、参工信息和年假折算。它不解释制度、不使用 Knowledge、不办理请假、不跳转页面、不修改员工数据，也不查询其他员工。

## 远端服务

Employee Data 以独立 A2A 服务部署在云 Runtime（当前版本 v11，`EMPLOYEE_DATA_BACKEND=stub`，有服务端可信身份 map/ref，已通过完整 AgentKit 远端验收；当前镜像 `agentkit-platform-2101533667-cn-beijing.cr.volces.com/agentkit/hr-agent-vkba:ec927bc-wp03-employee-balances-cdf7856146a1`）。不再提供本地三服务启动步骤。AgentCard 名称为 `hr-employee-data-agent`，版本 `1.0.0`，协议 `0.3.0`，提供本人余额、本人医疗期和本人年假折算三个 Skill。健康检查与 AgentCard 发现由 AgentKit 远端验收客户端在 `tests/agentkit` 下执行。

## 身份与数据源

身份链固定为：

```text
A2A user_id → TrustedIdentityResolver → 内部 employeeId → Gaia 只读查询
```

`provider_from_env` 按 `EMPLOYEE_DATA_BACKEND` 分支：`stub` 返回 `StubEmployeeDataProvider`（不读取 Gaia 四项）；`gaia` 才调用 `gaia_server_config_from_env()`。当前授权边界为 `EMPLOYEE_DATA_BACKEND=stub`。

| 变量 | 说明 |
|---|---|
| `EMPLOYEE_IDENTITY_MAP_JSON` | A2A `user_id` 到内部 employeeId 的服务端映射；留空必填，不得传给模型 |
| `EMPLOYEE_REF_SECRET` | 生成不可逆 `employee_ref` 的服务端共享身份密钥 |
| `EMPLOYEE_DATA_BACKEND` | `stub`（用户授权假数据）；不会自动回退 |
| `GAIA_CORP_ID` / `GAIA_CLIENT_SECRET` / `GAIA_GRANT_TYPE` / `GAIA_SCHEDULE_TENANT` | 真实 Gaia 服务端配置；仅 `gaia` 后端需要，`stub` 不读取 |
| `EMPLOYEE_DATA_STUB_JSON` | 授权 stub 配置：JSON 字符串（非文件路径），留空必填；成功响应必须 `source=stub` |

> 注意：Orchestrator 的公共 builder 在 `GAIA_BACKEND=stub` 且干跑时不再要求 Gaia 四项（云端已生效）；本 Agent 的 stub provider 不读取 Gaia 四项。公共 builder 的服务端可信身份与验证状态见 [`../../docs/agentkit-acceptance.md`](../../docs/agentkit-acceptance.md)。

A2A 请求不得包含 `employeeId` 或目标员工字段；`user_id` 不直接当作 employeeId。未建立可信映射返回 `identity_unverified`，跨员工请求返回 `cross_employee_query_not_allowed`。Artifact、日志和 Trace 只允许不可逆 `employee_ref`。

## 验证状态

真实 Gaia 连通性与 OAuth 缓存证据**尚未验证**，不计为已通过；当前授权边界为 `EMPLOYEE_DATA_BACKEND=stub`。WP01-WP07 在授权边界内 PASS（含双员工精确 medical 数据与不可逆 `employee_ref`、未映射/平台服务同 id 拒绝、多假种本人余额、医疗期/工龄/年假折算等）。当前验收入口是 `tests/agentkit` 下对已部署 Employee Data Runtime 的远端 HTTP 客户端用例，详见 [`../../docs/agentkit-acceptance.md`](../../docs/agentkit-acceptance.md)。
