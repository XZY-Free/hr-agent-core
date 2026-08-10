# Employee Data Agent应用

`hr_employee_data_agent`是独立只读Agent，只查询当前员工本人的假期余额、医疗期、参工信息和年假折算。它不解释制度、不使用Knowledge、不办理请假、不跳转页面、不修改员工数据，也不查询其他员工。

## 本地服务

```bash
uv run python -m apps.employee_data_agent
```

| 接口 | 地址 |
|---|---|
| 健康检查 | `http://127.0.0.1:8102/health` |
| AgentCard | `http://127.0.0.1:8102/.well-known/agent-card.json` |
| JSONRPC/SSE | `http://127.0.0.1:8102/` |

AgentCard名称为`hr-employee-data-agent`，版本`1.0.0`，协议`0.3.0`，提供本人余额、本人医疗期和本人年假折算三个Skill。

## 身份与数据源

身份链固定为：

```text
A2A user_id → TrustedIdentityResolver → 内部employeeId → Gaia只读查询
```

本地显式映射配置：

| 变量 | 说明 |
|---|---|
| `EMPLOYEE_IDENTITY_MAP_JSON` | A2A `user_id`到内部employeeId的服务端映射；不得传给模型 |
| `EMPLOYEE_REF_SECRET` | 生成不可逆`employee_ref`的服务端密钥 |
| `EMPLOYEE_DATA_BACKEND` | `gaia`或显式`stub`；默认`gaia`，不会自动回退Stub |
| `GAIA_CORP_ID` | Gaia服务端租户配置 |
| `GAIA_CLIENT_SECRET` | Gaia服务端密钥 |
| `GAIA_GRANT_TYPE` | Gaia服务端授权类型 |
| `EMPLOYEE_DATA_STUB_JSON` | 仅`EMPLOYEE_DATA_BACKEND=stub`时的本地测试数据 |

A2A请求不得包含`employeeId`或目标员工字段；`user_id`不直接当作employeeId。未建立可信映射返回`identity_unverified`，跨员工请求返回`cross_employee_query_not_allowed`。Artifact、日志和Trace只允许不可逆`employee_ref`。

独立Agent向模型公开`calc_annual_leave`和`get_medical_period`两个组合工具；底层员工信息和余额接口仍是工具内部依赖，不拆成额外Agent或模型工具。真实Gaia尚未验证；当前本地A2A证据均明确`source=stub`。
