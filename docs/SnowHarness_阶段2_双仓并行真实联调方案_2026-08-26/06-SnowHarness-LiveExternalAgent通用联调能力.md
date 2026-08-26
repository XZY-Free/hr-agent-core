# 06 — Track S1：SnowHarness Live External Agent 通用联调能力

## 1. 前置

必须先确认阶段1 `COMPLETE`。

若 AgentRevision source Authority、Capability-driven Registration、External Credential、Context、cancel、stream recovery、Studio任一未完成，先完成阶段1，禁止HR特例补丁。

## 2. Production红线

SnowHarness production代码禁止出现：

```text
hr-assistant
HR Agent
leave
employee data
consult
8100
veADK
AgentKit
```

作为行为分支。

阶段2新增能力必须对任意live external Agent通用。

## 3. Generic Live External Agent Runner

新增开发/集成工具，建议：

```text
scripts/integration/live-external-agent.ts
```

路径可按现有规范调整，但只保留一个正式runner。

用途：只用Public Contract文件 + Runtime Endpoint驱动SnowHarness正式控制面，不读Provider源码。

## 4. Runner输入

只允许：
```text
contract_file
runtime_endpoint
runtime_auth_mode
credential_ref_id?
admin_base_url
employee_base_url
```

可选测试输入manifest。

禁止：
```text
provider source dir
Git repo
framework
静态AgentCard作为live authority
employeeId
raw bearer token CLI参数
```

bearer必须走SnowHarness CredentialRef。

## 5. Runner正式调用链

只能调用正式API/worker：

```text
Register Agent Contract
→ Snapshot
→ Create AgentRevision
→ Publish AgentRevision
→ Register External Runtime
→ Publish RuntimeRevision
→ Create/Activate Route
→ Employee Thread
→ Employee Turn(agent_selection.required)
```

不得直接插DB制造Revision/Publication/Projection/Binding/Invocation。

## 6. Worker必须真实

如果控制面依赖outbox/projection worker：
- 启动真实worker；
- 不直接调用store伪造projection完成。

## 7. Idempotency

每次runner生成run id，每个write有稳定step key。

失败重跑不制造重复Agent/Runtime/Route。

已有stable identity时用正式查询和状态判断，不直接删DB。

## 8. Live Test Profile

Runner本身不认识HR。

测试case从外部manifest提供：
```text
basic_input
input_required_input
resume_input
expect_cancel_supported
expected_locale
```

如需提交fixture，只能在e2e/test边界，production不import。

## 9. Evidence

收集SnowHarness自身可见：
```text
agent_id
snapshot_id
agent_revision_id
agent_publication_record_id
runtime_revision_id
verification
route/revision/activation
invocation_id
runtime_session_ref
final turn state
```

不收provider source hash、secret、employeeId。

## 10. Failure

endpoint不可达 → fail closed，不切Test Provider。

AgentCard mismatch → fail。

resume不工作 → fail。

bearer失败 → fail，不fallback none。

required route不可用 → fail，不fallback base Harness。

## 11. Architecture Gate

production路径不得出现HR/8100/veadk/agentkit专属分支。

测试fixture文案可以出现HR，但只能在integration/e2e边界。

## 12. Tests

Runner自身可用generic仓内Provider做工具级单测，但Track S最终不能只靠它。

必须证明：
- runner不读provider source；
- 只走formal APIs；
- no direct DB writes；
- none/bearer输入规则；
- cancel expectation来自effective capability；
- 没有source-dir参数。

## 13. DoD

给任意合法Public Contract + endpoint + CredentialRef，SnowHarness无需production改造即可走正式控制面。
