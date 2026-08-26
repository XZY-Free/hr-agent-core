# SnowHarness 阶段 2：双仓并行真实联调方案

## 1. 目的

阶段 2 不再扩张 SnowHarness 核心架构，而是把阶段 1 已经收口的“通用黑盒 Agent 接入能力”与真实 `hr-agent-core` 公共 A2A Provider 接起来，并完成真正的双仓联调与 Web/Desktop 验收。

阶段 2 采取 **双仓并行**：

```text
Track H — hr-agent-core Provider 侧收口
                ╲
                 → Join Gate → 真实联调 → 最终验收
                ╱
Track S — SnowHarness Consumer / Live Integration 侧收口
```

两个 Track 可以在两个独立 Claude Code 会话中同时执行。

## 2. 方案编写事实基线

### hr-agent-core

```text
repository: XZY-Free/hr-agent-core
branch: main
commit: 5a3ec3ed359d8c1631aee2e28f20e49f917ae6be
```

### SnowHarness

方案编写时公开 main：

```text
repository: XZY-Free/harness
branch: main
commit: ad9daf9e6ae2c30f184316110781897b1bb437fd
```

但阶段 2 的 SnowHarness 实施基线 **不是 ad9daf9**。

必须：

```text
阶段 1 COMPLETE 后的当前 SnowHarness 工作区
= 阶段 2 SnowHarness 唯一事实源
```

禁止为了匹配本方案 checkout / rollback 到旧 SHA。

## 3. 阶段 2 前置 Gate

Track H 可以先开始，因为 Provider 侧修复建立在本方案冻结的跨仓合同上。

Track S 只有阶段 1 最终结论为 `COMPLETE` 后才允许开始写 SnowHarness 阶段 2 代码。若阶段 1 尚未完成，只允许只读审查，禁止绕过阶段 1 目标给 SnowHarness 打 HR Agent 特例补丁。

## 4. 本阶段最终拓扑

```text
SnowHarness
  ↓
stable Agent
  ↓
AgentContractSnapshot
  ↓
AgentRevision / Publication
  ↓
External RuntimeRevision
  ↓
Route / ExecutionBinding
  ↓
Allowed Invocation Context
  ↓
Outbound Runtime Credential
  ↓
A2A 0.3.0
  ↓
HR Orchestrator Public A2A Provider
  ↓
HR Orchestrator
  ├─ Leave business path
  ├─ A2A → Consult Agent
  └─ A2A → Employee Data Agent
```

SnowHarness 永远只看最外层 HR Assistant，不知道内部子 Agent、veADK、AgentKit、Tool、Skill、Router 或源码。

## 5. 文档

先读：
1. `00-阶段2主控与并行编排.md`
2. `01-跨仓A2A集成合同冻结.md`

hr-agent-core 会话再读：
3. `02-HR-A2A端点与运行配置Authority.md`
4. `03-HR-A2A认证与ExecutionSubject身份边界.md`
5. `04-HR-Context-Resume-Cancel与结果语义.md`
6. `05-HR-注册工件-测试与Provider验收.md`

SnowHarness 会话再读：
7. `06-SnowHarness-LiveExternalAgent通用联调能力.md`
8. `07-SnowHarness-WebDesktop真实联调验收入口.md`

两个 Track 都 PASS 后：
9. `08-双仓JoinGate与真实E2E矩阵.md`
10. `09-回归-安全-最终只读审计.md`
11. `10-并行分支与合并纪律.md`

启动提示词：
- `Claude-Code-HR-Track启动提示词.md`
- `Claude-Code-SnowHarness-Track启动提示词.md`
- `Claude-Code-JoinGate最终联调提示词.md`

## 6. 本阶段不做

- 不重构 HR Agent 内部多 Agent 架构；
- 不把 Consult / Employee Data 注册成 SnowHarness Agent；
- 不把 HR capability 改成 Tool；
- 不实现 A2A 1.x；
- 不实现 durable task recovery；
- 不为 HR Agent 加 SnowHarness 专属 production adapter；
- 不让 SnowHarness 读取 `hr-agent-core` 源码；
- 不把 `hr-agent-core` 文件复制进 SnowHarness；
- 不新建第二 Route / Binding / Invocation 系统；
- 不把真实用户 employeeId 发给 SnowHarness；
- 不在 git 中提交真实 token / employee mapping；
- 不用 mock Provider 代替阶段 2 最终 E2E。

## 7. Authority

冲突优先级：

```text
00 主控
>
01 跨仓合同
>
各 Track 专项
```

代码路径变化时，修改当前唯一正式职责实现，不因路径变化创建第二套。
