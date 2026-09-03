# WP-01 身份与 Gaia 执行上下文整改

## 1. 目标

把当前两套不一致的身份模型收敛成一套：

```text
SnowHarness ExecutionSubject
        ↓
PublicIdentityAdapter
        ↓
internal_user_id（伪匿名稳定ID）
        ↓
Trusted HR Identity Resolver
        ↓
employee_id / employee_ref
        ↓
服务端 Gaia Provider / Config
        ↓
Leave / Employee Data 共用
```

本专题完成后：

- SnowHarness 不传 employee_id；
- 公共 A2A 不接受 employee_id；
- Agent 对话不携带 Gaia secret；
- Leave 与 Employee Data 采用同一可信身份解析规则；
- Gaia corp/secret/grant_type/tenant 都来自服务端；
- ADK session state 不再是 Gaia 凭据的 Authority。

---

## 2. 当前已确认问题

### 2.1 公共身份只完成了伪匿名映射

`apps/orchestrator/public_runtime/identity_adapter.py`

当前职责：

```text
ExecutionSubject -> snowharness-<hash>
```

并且明确不负责 employee_id 映射。

这个方向是正确的，**不要删除，也不要直接改成 employee_id**。

### 2.2 Employee Data 已经有第二段可信解析

`apps/employee_data_agent/identity.py`

当前有：

```text
internal_user_id -> employee_id
```

并生成不泄露 employee_id 的 `employee_ref`。

这部分是正确资产，应上移/共享，而不是在 Leave 再做一份。

### 2.3 Leave 仍依赖旧 session state

当前 Gaia 读取路径集中在：

- `packages/hr_domain/gaia/client.py`
- `packages/hr_domain/gaia/leave_query.py`
- `packages/hr_domain/gaia/employee_query.py`
- `packages/hr_domain/gaia/schedule_query.py`

其生产路径仍依赖：

- `state["employeeId"]`
- `state["corp_id"]`
- `state["client_secret"]`
- `state["grant_type"]`

而公共 Local Runner 只收到：

- `messages`
- `user_id`
- `session_id`

这就是断层。

---

## 3. 目标架构——必须按此实施

### 3.1 共享 Trusted HR Identity

将 Employee Data 当前的可信身份解析能力提升为共享领域基础设施。

目标位置：

```text
packages/hr_domain/identity/
```

职责只包括：

1. 根据 `internal_user_id` 查可信映射；
2. 得到 `employee_id`；
3. 生成 `employee_ref`；
4. 未映射时 fail closed。

现有：

`apps/employee_data_agent/identity.py`

完成迁移后不能继续保留一套独立的第二 Authority。

允许保留薄 re-export 只在迁移过程短暂存在；本 WP 结束时生产代码必须只认共享 Authority。

---

### 3.2 共享 Gaia Server Config

新增共享服务端配置对象，Authority 放到：

```text
packages/hr_domain/gaia/
```

必须包含：

- `corp_id`
- `client_secret`
- `grant_type`
- `schedule_tenant`

环境变量沿用/新增：

- `GAIA_CORP_ID`
- `GAIA_CLIENT_SECRET`
- `GAIA_GRANT_TYPE`
- `GAIA_SCHEDULE_TENANT`

要求：

- `GAIA_SCHEDULE_TENANT` 不再在 `schedule_query.py` 写死 `snowbeertest`；
- 本轮不改变现有各查询接口使用 prod/sandbox 的业务环境选择，避免把环境切换和身份整改混在一起；
- 缺少生产必需配置时 fail closed；
- stub 仍只能显式开启，不能自动 fallback。

---

### 3.3 共享 Gaia Provider

把“工具自己从 state 拼 GaiaClient”改成：

```text
Request-bound HR Execution Context
        ↓
Gaia Provider
        ├── employee_info
        ├── medical_period
        ├── leave_balances
        ├── leave_permissions
        └── schedule
```

Provider 的调用者只提供业务参数，不提供：

- corp_id；
- secret；
- grant_type；
- employee_id（除 Provider 内部已可信解析的结果）。

这一步的核心不是增加抽象层，而是消除：

```text
任意 tool_context.state -> Gaia credential
```

这种不安全 Authority。

---

### 3.4 Request-bound Execution Context

在当前一次请求执行期间绑定：

- `internal_user_id`
- 可信 identity resolver
- Gaia provider/config
- 当前 `request_id`
- 当前 `context_id`

工具需要当前员工身份时，调用共享上下文的：

```text
require_employee_identity()
```

语义要求：

- 当前消息只是问候/普通咨询，不需要 employee identity 时，不因为未映射而提前失败；
- 当 Leave / Employee Data 真正访问本人业务数据时才要求解析；
- 未映射时返回稳定 `identity_unverified`；
- 严禁 fallback 到 `user_id == employee_id`。

可以采用 request-scoped binding / ContextVar 形态；具体实现形式不得改变上述语义。

---

## 4. 必须修改的现有模块

### 4.1 `apps/orchestrator/public_runtime/identity_adapter.py`

保留：

```text
ExecutionSubject -> internal_user_id
```

不得：

- 返回 employee_id；
- 读取 Gaia credential；
- 读取 EMPLOYEE_IDENTITY_MAP_JSON。

它仍然只负责公共主体命名空间隔离。

### 4.2 `apps/orchestrator/public_a2a/server.py`

`build_runtime()` 需要装配共享的：

- HR identity resolver；
- Gaia provider / server config；
- Local Runner request binding。

当前：

```text
HrAssistantRuntime(remote_router, local_runner)
```

需要扩展为能够让 Local Leave 在执行期间获得可信 HR execution context。

不要把配置文本拼进用户消息。

### 4.3 `apps/orchestrator/public_runtime/runtime.py`

本地执行时：

1. 已有 `internal_user_id` 继续作为 Runner user_id；
2. 在调用 `local_runner.run` 前建立 request-scoped HR execution context；
3. 不把 employee_id 写进 Prompt；
4. 不把 client_secret 写进 session；
5. 不因为一个匿名问候而强制 resolve employee；
6. Leave 工具真正访问 Gaia 时再 fail closed。

### 4.4 `apps/employee_data_agent/identity.py`

把实现迁到共享层。

Employee Data Runtime 改为 import 共享 resolver。

最终不得有：

```text
Employee Data 一套 TrustedIdentityResolver
Leave 又一套 LeaveIdentityResolver
```

### 4.5 `apps/employee_data_agent/provider.py`

现有 `GaiaEmployeeDataProvider._context()` 会人为构造：

```text
SimpleNamespace(state={
 employeeId,
 corp_id,
 client_secret,
 grant_type
})
```

整改后删除这种“为了兼容旧工具而伪造 state”的方式。

Employee Data Provider 直接通过共享 Gaia Provider 访问数据。

### 4.6 `packages/hr_domain/gaia/client.py`

当前 `from_state(state)` 不能继续作为生产 Authority。

整改要求：

- GaiaClient 仍可保留；
- ConfiguredGaiaStubClient 仍可保留；
- 生产工具不再从任意 ADK state 构造 GaiaClient；
- 共享 Provider 从服务端 Config 构造/复用客户端；
- 本 WP 完成后若 `from_state` 没有生产用途，删除，不保留“以后可能有用”的兼容层。

### 4.7 `packages/hr_domain/gaia/*.py`

以下工具改为通过共享 Provider / request binding 获取：

- 当前 employee identity；
- Gaia client；
- corp / tenant。

工具签名仍应以业务参数为中心。

例如排班业务只应该关心：

```text
start_date
end_date
```

而不是要求模型/会话提供 employeeId、secret。

---

## 5. 身份错误语义

必须稳定区分：

### `identity_unverified`

含义：

> 调用主体存在，但无法映射为当前员工身份。

适用于：

- SnowHarness subject 没有配置 HR employee mapping；
- platform service 没有可办理个人业务的 HR identity。

不得改成：

- employee_not_found；
- Gaia unavailable；
- anonymous employee；
- 使用 subject_id 直接查 Gaia。

### `gaia_auth_failed`

含义：

> 已有可信 employee identity，但服务端 Gaia 凭据认证失败。

### `gaia_unavailable`

含义：

> 身份和服务端配置均正常，但 Gaia 服务不可用。

---

## 6. 安全强制项

以下任何一条出现，WP-01 直接判失败：

- Public Request 新增 `employee_id`；
- Public Request 新增 `corp_id`；
- Public Request 新增 `client_secret`；
- Prompt 中出现真实 Gaia secret；
- session state 持久保存真实 client_secret；
- 日志记录 employee_id；
- 把 pseudonymous internal_user_id 当作 Gaia employee_id；
- identity resolve 失败时自动使用测试员工；
- Gaia 失败时自动切 stub；
- Consult 可以从用户文本拿员工编号再查询。

---

## 7. 单元测试要求

至少覆盖：

### 公共主体

1. 同一 ExecutionSubject -> 同一 internal_user_id；
2. 不同 subject -> 不同 internal_user_id；
3. platform_user / platform_service 相同 subject_id -> 不同 internal_user_id；
4. 无 execution_subject -> anonymous；
5. 请求正文中出现 employee_id 类敏感字段仍 contract_error。

### Trusted HR Identity

6. 已配置 internal_user_id -> 正确 resolve；
7. 未配置 -> `identity_unverified`；
8. employee_ref 稳定；
9. 日志和 repr 不泄露 employee_id。

### Leave request-bound context

10. 问候不要求 identity；
11. 请假一旦调用权限/排班/余额工具，必须 resolve；
12. identity_unverified 时 Gaia 不得被调用；
13. resolved identity 时工具收到正确员工；
14. local resume 同一 task 不丢 identity binding；
15. 下一任务不能继承上一个任务的 employee identity 实例状态。

### Gaia 配置

16. 生产配置缺失 fail closed；
17. `GAIA_SCHEDULE_TENANT` 缺失时生产启动失败；
18. stub 仅显式配置可用；
19. 生产 Gaia 失败不回退 stub；
20. 服务端 credential 不进入 ToolResult。

---

## 8. 集成验收场景

### 场景 A：本人年假查询

```text
ExecutionSubject
 -> internal_user_id
 -> trusted employee_id
 -> Employee Data
 -> Gaia
```

要求：

- 调用方完全不知道 employee_id；
- 响应只出现 employee_ref；
- 数字来自 Gaia/Stub provider。

### 场景 B：本人请假

```text
ExecutionSubject
 -> internal_user_id
 -> local Leave
 -> shared identity resolver
 -> Gaia permission/schedule/balance
```

要求：

- 不依赖 session 中预塞 employeeId；
- 权限/排班/余额三个工具解析到同一员工；
- request 结束后 request-scoped binding 清理。

### 场景 C：匿名咨询

```text
无 ExecutionSubject
 -> 普通 HR policy query
 -> Consult
```

要求：

- 可以回答公共制度；
- 不因为 HR identity 缺失而失败。

### 场景 D：匿名本人业务

```text
无 ExecutionSubject
 -> “我的年假还有多少” / “帮我请假”
```

要求：

- 返回 identity_unverified；
- 不访问任意测试用户。

---

## 9. 完成门禁

WP-01 结束前必须满足：

- Leave 与 Employee Data 共享一个 HR identity Authority；
- 生产 Gaia 凭据只来自服务端；
- `from_state` 不再被生产 HR 业务工具使用；
- 本地 Leave 在公共 A2A 下可拿到可信员工；
- 公共契约仍不接受 HR 主键和 credential；
- 全部新增安全测试通过。

完成后再进入 WP-02。
