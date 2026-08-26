# SnowHarness 注册说明 — 企业人力智能助手

- 稳定身份：`hr-assistant`（公共版本 `1.0.0`）
- Runtime 端点：`https://hr-assistant.example.invalid/`
- 协议：A2A 0.3.0（JSON-RPC over HTTP，SSE流式事件通道）
- 认证方式：当前为 none（无强制认证；接入方按运行时实际配置填写）

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

执行主体（execution_subject）不传 employee_id / corp_id / 任何内部凭据；
身份映射由智能体内部完成，未验证身份返回稳定 `identity_unverified`。

## 注册步骤

1. **导入合同工件**：管理员将 `agent-contract.json` 作为一次性请求输入
   导入SnowHarness。SnowHarness解析后以结构化字段（身份、能力、
   交互声明、结果合同等）存入数据库并返回 `contract_snapshot_id`；
   原始合同文件是瞬时输入，SnowHarness不整体存储该文件，也不需要
   再次读取它。
2. **提交运行时注册**：运营方将 `runtime-registration.example.json` 中
   的占位符 `<contract_snapshot_id-from-contract-import>` 替换为上一步返回的真实ID，
   填入实际 `runtime_endpoint` 与认证配置后提交。
3. **执行Conformance**：SnowHarness主动调用运行时，期间只拉取标准
   AgentCard（`/.well-known/agent-card.json`）作为协议证据，按
   `conformance` 输入执行真实对话验证（start触发补充信息提示，
   resume为补充说明文本，不含确认或提交动作）。

运行时不提供远程合同端点；`agent-contract.json` 只通过上述导入步骤
进入SnowHarness，不由平台从运行时拉取。本包不附带任何由提供方
生成的测试结论。
