# SnowHarness 注册说明（Operator Runbook）— 企业人力智能助手

- 稳定身份：`hr-assistant`（公共版本 `1.0.0`）
- 协议：A2A 0.3.0（JSON-RPC over HTTP，SSE流式事件通道）
- 交互能力（与运行时一致，不得漂移）：
  `streaming=true, incremental=false, inputRequired=true, resume=true,
  cancel=false, durable=false`
- 静态示例端点：`https://hr-assistant.example.invalid/`（仅示例；live AgentCard只能HTTP discovery）

## 能力摘要（任务领域，非函数列表）

| 稳定键 | 名称 |
|---|---|
| `leave-and-attendance-service` | 假勤与请假服务 |
| `employee-self-service` | 员工本人信息服务 |
| `hr-policy-and-benefits-consultation` | 人力制度与福利咨询 |
| `hr-system-and-document-assistance` | 人力系统与文档协助 |

## 调用上下文合同摘要

| 上下文 | 必要性 |
|---|---|
| `execution_subject` | preferred |
| `timezone` | preferred |
| `current_datetime` | preferred |
| `locale` | preferred |
| `conversation_summary` | preferred |
| `attachment_references` | accepted |

执行主体（execution_subject）只含 `subject_id` + `subject_kind`
（`platform_user` / `platform_service`），不传 employee_id / corp_id /
任何内部凭据；身份映射在智能体私有层完成，未验证身份返回稳定
`identity_unverified`。

## Operator 注册步骤

1. **启动 Public A2A**：设置
   `HR_ASSISTANT_A2A_HOST/PORT/PUBLIC_URL/AUTH_MODE`（见 `.env.example`）
   并启动 hr-assistant 公共A2A进程。
2. **health**：`GET <public_url>/health` 确认
   `status/agent/version/protocol_version/auth_mode`。
3. **live AgentCard**：`GET <public_url>/.well-known/agent-card.json`。
   `card.url` 就是JSON-RPC端点；SnowHarness 的 `runtime_endpoint`
   与 `card.url` 规范化后必须一致。静态 `agent-card.example.json`
   不是live authority。
4. **导入agent-contract**：管理员将 `agent-contract.json` 作为一次性
   请求输入导入SnowHarness，得到 `contract_snapshot_id`。
5. **AgentRevision**：在SnowHarness中基于导入的合同创建AgentRevision。
6. **Runtime Registration**：把 `runtime-registration.example.json` 中
   `<contract_snapshot_id-from-contract-import>` 替换为真实ID，`runtime_endpoint` 替换为
   live `card.url`，认证按实际配置填写后提交。
7. **Publication**：发布该AgentRevision/RuntimeRevision。
8. **Route**：在SnowHarness中配置Route/ExecutionBinding与允许的
   Invocation Context。
9. **Employee选择**：员工在SnowHarness中选择该Agent发起会话。
10. **input-required/resume**：用 `conformance` 固定输入验证
    input-required 与 same task/context resume。
11. **cancel=false预期**：Conformance不跑cancel探针；UI无Stop；
    直接调用 `tasks/cancel` 会收到官方unsupported-operation错误。
12. **bearer可选**：`HR_ASSISTANT_A2A_AUTH_MODE=bearer` 时必须配置
    `HR_ASSISTANT_A2A_BEARER_TOKEN`，并在SnowHarness用CredentialRef
    引用凭据；禁止把真实token写进任何工件或git。

## Subject → 内部映射（operator私下操作）

- HR侧用 `scripts/public_subject_ref.py --subject-kind platform_user
  --subject-id <snow-subject-id>` 计算 internal_user_id；
- 管理员私下在 `EMPLOYEE_IDENTITY_MAP_JSON` 配置
  `internal_user_id → employeeId`；
- SnowHarness永不拥有employeeId，也不得保存/传递。

运行时不提供远程合同端点；`agent-contract.json` 只通过上述导入步骤
进入SnowHarness。本包不附带任何由提供方生成的测试结论。
