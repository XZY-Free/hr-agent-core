# 新批次4 本地多 Agent 与 A2A 报告

> 最终状态修正：本文保留新批次4的迁移期事实。新批次5已在云端双轨清理前后分别取得21/21，生产Orchestrator中的local Consult、local Employee Data和transport切换已删除。当前运行手册以根`README.md`、`deployment/README.md`和`docs/cloud-deployment-report.md`为准。

检查时间：2026-08-10（Asia/Shanghai）

起点：`051a8e2 feat: expose consult agent as standalone a2a service`

## 1. 本地运行形态

```text
hr-orchestrator（127.0.0.1:8000）
├── 本地 leave_agent
├── 本地 page_jump、取消引导、人工入口和固定交互
├── A2A JSONRPC → hr-consult-agent（127.0.0.1:8101）
└── A2A JSONRPC → hr-employee-data-agent（127.0.0.1:8102）
```

本批只完成本地服务与显式 A2A。没有运行`agentkit launch`，没有创建、更新或删除 Runtime、A2A Space、A2A Agent、API Key、IAM角色和其他云资源。Leave Agent仍在Orchestrator进程内。

| 依赖 | 锁定版本 |
|---|---|
| `agentkit-sdk-python` | `0.8.1` |
| `veadk-python` | `1.1.0` |
| `google-adk` | `2.2.0` |
| `a2a-sdk[http-server]` | `0.3.7` |

## 2. Employee Data Agent

### 工具与职责

审计时`build_employee_data_tools()`的既有返回顺序为：

```text
get_leave_balance
get_medical_period
calc_annual_leave
```

为保持`local/local`的21条基线不变，这个兼容集合没有改名或删减。独立`hr_employee_data_agent`只向模型公开：

```text
calc_annual_leave
get_medical_period
```

余额、员工信息和参工日期由组合工具内部读取；写工具为0。Agent不装配Knowledge、文档解析、请假、页面跳转或员工修改能力。

### 身份与Gaia边界

```text
A2A user_id
→ 服务端 TrustedIdentityResolver
→ 内部 employeeId
→ EmployeeDataProvider
→ Gaia只读接口
```

- A2A请求不接收`employeeId`或`target_employee_id`；自然语言和metadata出现这些字段时在Agent前拒绝。
- `user_id`不直接作为`employeeId`。未命中显式映射返回`identity_unverified`。
- 查询其他员工返回`cross_employee_query_not_allowed`。
- 原始`employeeId`只在服务端身份解析与Provider调用期间存在，不进入提示词、Artifact、证据日志或Trace；外部只见HMAC生成的`employee_ref`。
- Gaia的`corp_id`、`client_secret`、`grant_type`和JWT只由Employee Data服务端配置持有。
- 本地门禁使用两个明确测试身份和`StubEmployeeDataProvider`，所有成功/失败结果均标记`source=stub`。这不代表企业SSO、AgentKit Identity或真实Gaia已完成。

### AgentCard与Skills

| 字段 | 值 |
|---|---|
| ADK名称 | `hr_employee_data_agent` |
| A2A名称 | `hr-employee-data-agent` |
| 版本 | `1.0.0` |
| 协议 | `0.3.0` |
| Transport | `JSONRPC` |
| streaming | `true` |
| 地址 | `http://127.0.0.1:8102/` |

| Skill ID | 作用 |
|---|---|
| `employee-leave-balance-query` | 查询本人假期余额 |
| `employee-medical-period-query` | 查询本人医疗期 |
| `employee-annual-leave-calculation` | 查询工龄并计算本人年假 |

DataPart固定包含`request_id`、`status`、`answer`、`query_type`、`data`、`data_as_of`、`source`、`employee_ref`、`partial`、`agent_name`、`agent_version`、`error_code`和`retryable`。`data_as_of`在每次请求处理时生成。

## 3. Orchestrator显式路由

仅有两个迁移开关：

| 环境变量 | 值 | 行为 |
|---|---|---|
| `HR_CONSULT_TRANSPORT` | `local` / `a2a` | Consult本地子Agent或8101 A2A |
| `HR_EMPLOYEE_DATA_TRANSPORT` | `local` / `a2a` | 本地工具或8102 A2A |

默认值均为`local`。只有显式设置`a2a`才调用远端；远端失败时不静默回退本地。

固定优先级：

| 优先级 | 意图 | 目标 |
|---|---|---|
| 1 | 请假申请、修改和请假多轮 | 本地Leave |
| 2 | 取消、撤回 | 本地页面引导 |
| 3 | 本人余额、医疗期、工龄、年假折算 | Employee Data A2A |
| 4 | 打开页面 | 本地`page_jump` |
| 5 | 制度、政策、福利、系统操作、文档 | Consult A2A |
| 6 | 人工服务 | 本地人工入口 |
| 7 | 闲聊 | 本地Orchestrator |

路由由确定性规则执行，不让模型在两个远端Agent间自由选择。本批没有A2A Space语义发现。

## 4. A2A请求与响应校验

Orchestrator发出的业务上下文只有：

```text
request_id
user_id
session_id
caller_agent=hr_orchestrator
locale=zh-CN
message
context_summary
```

禁止发送`employeeId`、`corp_id`、`client_secret`、`grant_type`、Gaia JWT、Runtime API Key、模型Key、火山AK/SK、完整`session.state`、系统提示词和完整历史消息。

消费者依次验证AgentCard名称/版本、Task状态、Artifact、DataPart、必填字段、`request_id`、业务状态、敏感字段和关键数字。未知且不敏感的响应字段兼容。Knowledge成功回答必须包含真实`source/score`；文档解析不伪造Knowledge来源。Employee Data关键数字必须同时存在于确定性工具`data`和面向用户的`answer`。

固定失败行为：

| 场景 | 用户侧结果 |
|---|---|
| Consult超时、鉴权失败、500、不可用或非法Artifact | 咨询服务暂时繁忙，不编造制度 |
| Consult无可靠结果 | 明确暂未查询到可靠制度 |
| Employee Data超时、鉴权失败、500、不可用或非法Artifact | 本人数据暂时无法查询，不返回历史数字 |
| 身份未验证 | 当前身份无法完成本人数据查询 |
| `request_id`不一致、敏感字段、关键数字不一致 | 拒绝使用远端结果并记录契约/安全错误 |

## 5. 本地端到端与故障注入

两个transport均设为`a2a`，真实启动8000、8101、8102并通过HTTP/SSE和官方A2A客户端验证：

| 输入 | 实际目标 |
|---|---|
| 迟到扣款制度是什么 | Consult A2A |
| 四川育儿假有几天 | Consult A2A |
| 育儿假有几天 | Consult A2A并追问省份 |
| 我还有几天年假 | Employee Data A2A |
| 我的医疗期余额 | Employee Data A2A |
| 我的年假怎么折算 | Employee Data A2A |
| 明天请一天年假 | 本地Leave，无A2A |
| 打开打卡明细 | 本地`page_jump`，JUMP保留 |
| 取消昨天的请假 | 本地页面引导，JUMP保留 |
| 转人工 | 本地人工入口，无A2A |

同一session的“育儿假有几天”→“四川”保持路由到Consult；不同用户、不同session的Consult与Employee Data并发请求使用不同`request_id`，没有串用。根session不存在时不发送A2A，交还AgentKit按原会话协议报错。

故障注入覆盖Consult/Employee服务关闭、A2A超时、鉴权失败、HTTP 500、空Artifact、缺少DataPart、Agent名称错误、版本缺失、`request_id`不一致、未知字段、敏感字段和关键数字不一致。所有失败均为目标专用安全话术，没有本地实现兜底。

## 6. 测试结果

| 门禁 | 结果 | 外部边界 |
|---|---|---|
| Employee Data独立评测 | 3 passed | 真实模型 + 显式Stub |
| Employee Data本地A2A | 17 passed | 真实8102网络 + 官方客户端 + Stub |
| Consult独立评测 | 10 passed | 真实模型 + 真实Viking |
| Consult本地A2A | 14 passed | 真实8101网络 + 官方客户端 + 真实Viking |
| 根入口`local/local` | 21 passed | 真实模型 + 真实Viking；Gaia与文档下载沿既有Stub |
| 根入口`a2a/a2a` | 21 passed | 三服务真实网络；Consult真实Viking；Employee/Gaia Stub |
| 固定三服务端到端 | 14 passed | 10个固定路由 + 同session + 并发session + 健康/SSE/JUMP + session不存在 |
| 非评测套件 | 236 passed，71 skipped，34 deselected | 条件型真实外部测试另行执行 |
| 真实Viking | 5 passed | 官方公开SDK |
| 故障与响应外壳 | 52 passed | 本地注入，不冒充真实云故障 |

最新脱敏本地证据（Git忽略）：

- `tests/e2e/logs/local-multi-agent-a2a-20260810-100246.jsonl`
- `tests/e2e/logs/employee-data-a2a-20260810-094443.jsonl`
- `tests/e2e/logs/consult-a2a-real-20260810-094252.jsonl`
- `tests/eval/logs/employee-data-eval-20260810-094412.jsonl`
- `tests/eval/logs/consult-eval-20260810-094142.jsonl`
- `tests/eval/logs/eval-20260810-100541.log`

本地日志记录脱敏`request_id`、目标、状态、工具名、来源类型、错误码和耗时；不记录Knowledge切片正文、原始employeeId、凭据或完整session。未启用云端Trace exporter，所以本地request ID证据不冒充跨Runtime Trace。

## 7. 未验证项与云端前置条件

未验证：真实Gaia、企业SSO/AgentKit Identity、持久Session、Runtime重启、多实例一致性、跨Runtime A2A与Trace、云端A2A鉴权、A2A Space语义发现、AgentKit控制台分析，以及Skill/MCP/长期Memory。

新批次5任何云端写操作前仍必须提交资源规格、地域、实例数、计费、凭据/IAM、部署顺序、回滚/销毁、现有线上影响和本地测试报告，并等待“允许开始云端部署”。计划资源仅登记在`deployment/resource-inventory.example.yaml`，当前均未创建。

## 8. 与批准指令的差异

无核心边界偏差。既有`build_employee_data_tools()`包含3个本地兼容工具，而独立Agent按批准边界只公开2个模型工具；该事实已在开工审计中记录，`local/local`行为与21条业务评测保持不变。真实Gaia因无可用凭据未执行，明确标为未验证。
