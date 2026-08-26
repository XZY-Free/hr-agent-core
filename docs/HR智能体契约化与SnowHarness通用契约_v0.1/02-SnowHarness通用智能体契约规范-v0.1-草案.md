# 02 — SnowHarness 通用智能体契约规范 v0.1（草案）

> 本规范从真实 HR Agent 项目中抽象，但规范本身不得依赖任何 HR、veADK、AgentKit 或具体业务实现。
>
> v0.1 先作为草案。
>
> 必须至少经过一个真实 Agent 改造 + SnowHarness 真联调后，才升级为正式规范并固化成 Codex Skill。

---

# 一、规范目标

任何智能体项目，无论内部使用：

- 单智能体；
- 多智能体；
- 任意Agent框架；
- 自研Loop；
- 云端Runtime；
- 本地Runtime；
- 闭源服务；

只要要被 SnowHarness 当作黑盒 Agent 使用，就必须能形成一套公开、机器可读、可验证的公共合同。

最终：

```text
Agent源码项目
    ↓
契约生成/改造工具可以读源码
    ↓
公开Agent Contract
    ↓
SnowHarness
```

冻结：

> 契约生成工具可以知道源码；SnowHarness 永远不依赖源码。

---

# 二、公共合同最小组成

完整公共合同由五部分组成：

```text
1. 智能体身份合同
2. 能力清单
3. 调用上下文合同
4. 协议与交互合同
5. 结果合同
```

对于 A2A Agent，至少公开：

```text
/.well-known/agent-card.json
/.well-known/agent-contract.json
```

第一份遵循 A2A 标准。

第二份承载 SnowHarness 需要、但标准 AgentCard 不足以完整表达的通用合同信息。

---

# 三、智能体身份合同

必须包含：

- stable agent id；
- display name；
- description；
- public version；
- provider；
- contract version。

要求：

- 公共身份不能使用内部 `root_agent`、进程名、Pod名；
- 内部重构不能无故改变公共稳定身份；
- 公共版本代表外部行为合同，不代表内部某个包版本。

---

# 四、能力清单

能力（Capability，智能体声明自己擅长处理的任务领域）用于：

- 人工选择；
- 搜索；
- 能力目录；
- 未来自动 Agent Discovery；
- 使用说明。

每项建议字段：

```text
id
name
description
tags
examples
input_modes
output_modes
```

---

# 五、能力不得 Tool 化

禁止：

```text
getLeaveBalance(employeeId, year)
queryOrder(id)
createContract(type, date)
```

直接成为公共 Agent Capability。

判断原则：

> 如果“能力”天然像一个函数签名，它大概率已经太细。

Agent Capability 应表达：

```text
任务领域
任务范围
典型问题
```

Tool/Function Operation属于Agent内部。

---

# 六、调用上下文合同

调用上下文合同（Invocation Context Contract，声明调用整个 Agent 时平台可提供的通用上下文）是 Agent 级合同。

不是每个 Capability 的函数参数 Schema。

每项至少包含：

```text
kind
necessity
purpose
applies_to
trust_requirement
declaration_source
```

其中代码标识的具体命名由机器Schema冻结。

---

# 七、上下文必要程度

第一版支持：

```text
required
preferred
accepted
```

## 必需

`required`

含义：

> 不存在该上下文时，整个Agent无法正确或安全开始调用。

必须极少使用。

如果只有部分业务任务需要，不应轻易定义成全局 required。

## 优先提供

`preferred`

含义：

> 平台拥有且策略允许时尽量提供；没有仍可调用Agent。

## 可接受

`accepted`

含义：

> Agent能够利用，但不应默认全量发送。

---

# 八、适用能力范围

允许：

```text
applies_to
```

声明某类 Context 主要服务哪些 Capability。

但必须明确：

> `applies_to` 不等于把 Agent 变成按 Capability RPC 调用。

第一版自然语言 Agent Invocation 仍然只调用整个 Agent。

SnowHarness 不得为了决定上下文而偷偷建立一套“先调用分类器，再调用Capability函数”的强制体系。

---

# 九、上下文最小化原则

真实发送 Context 必须是：

```text
Agent声明
∩
当前平台实际拥有
∩
租户策略允许
∩
调用者权限允许
∩
数据出域规则允许
```

冻结：

```text
Agent Wants
≠
Platform Allows
```

Agent 不能通过 Descriptor 自己授予数据权限。

---

# 十、可信上下文

某些 Context 必须带可信来源属性，例如：

```text
execution_subject
```

执行主体（ExecutionSubject，表示本次执行由平台确认的真实调用者身份）不能由：

- 用户自然语言；
- 前端自由字段；
- Agent声明；

直接伪造。

必须来自平台认证 Authority。

---

# 十一、常见 Context Kind

v0.1 不无限预造。

建议首批：

```text
execution_subject
current_datetime
timezone
locale
conversation_summary
attachment_references
workspace_context
organization_context
```

后续 Context / Memory / Knowledge 专题成熟后再扩充。

所有类型必须复用 SnowHarness 现有 Context Authority，不建立第二套 Context 数据系统。

---

# 十二、业务信息仍由 Agent 自己理解

SnowHarness 负责：

```text
上下文富化
```

Agent负责：

```text
任务理解
业务补参
规划
内部Tool
内部子Agent
```

例如：

```text
“帮我申请假”
```

缺日期、类型属于业务任务信息。

Agent应该：

```text
input-required
```

而不是要求 SnowHarness 预先知道其内部 Tool 参数表。

---

# 十三、公共请求语义

调用整个 Agent 的内部平台语义应保持：

```text
original task
+
allowed context bundle
```

而不是：

```text
capability name
+
function args
```

Runtime Transport 负责映射到具体协议。

---

# 十四、公共合同来源

公共合同可以来自：

```text
provider_declared
operator_declared
```

提供方声明（`provider_declared`，由Agent自身公开提供）优先。

管理员声明（`operator_declared`，由管理员根据正式接入资料补充）必须：

- 明确标识；
- 进入不可变Snapshot；
- 参与Digest；
- 不伪装成Agent自身声明。

---

# 十五、能力声明不是能力证明

必须区分：

```text
Declared
Verified
Evaluated
```

中文语义：

- 声明：Provider说自己支持；
- 验证：协议/运行测试确实观察到；
- 评测：业务质量测试证明效果达到标准。

例如：

```text
“支持流式”
```

必须经过运行验证才能标为 verified。

```text
“能准确回答制度问题”
```

属于业务评测，不属于Runtime Conformance。

---

# 十六、协议能力必须细分

至少区分：

## 流式传输

```text
streaming_transport
```

表示可以通过流式连接持续接收任务事件。

## 内容增量

```text
incremental_content
```

表示正文/Artifact真实分块逐步产生。

二者不得混为一谈。

---

# 十七、等待用户补充

如果Agent真的缺业务信息，应支持：

```text
input-required
```

SnowHarness收到后：

- Invocation进入等待用户；
- UI展示缺失信息说明；
- 用户继续输入；
- Resume原Invocation；
- 不新建无关Task。

---

# 十八、恢复

恢复（Resume，继续原有远端任务和上下文）至少应证明：

```text
same taskId
same contextId
new user input
→ task continues
```

如果Provider只支持新建Task，不得宣称Resume。

---

# 十九、取消

取消支持必须通过真实行为证明。

不能因为代码存在：

```text
cancel()
```

就声明支持取消。

至少验证：

```text
long-running work
→ cancel
→ active work stops
→ cancelled terminal state
→ no later success
```

---

# 二十、持久任务恢复

必须单独声明：

```text
durable_task_recovery
```

只有服务重启后仍能：

- 查到任务；
- 继续/取消任务；
- 保持正确状态；

才可以标为 true。

进程内 TaskStore 不满足。

---

# 二十一、会话与任务分离

长期语义：

```text
contextId
= 远端连续会话

taskId
= 本次具体任务
```

一个 contextId 可以包含多个 taskId。

禁止长期：

```text
contextId = taskId
```

---

# 二十二、认证与业务上下文分离

Runtime认证：

```text
Authorization Header
mTLS
OAuth
managed secret
```

不得进入：

- 用户Task文本；
- Context summary；
- Artifact；
- Agent Capability。

Secret不属于 Invocation Context。

---

# 二十三、结果合同

Agent必须至少提供人类可读结果。

推荐：

```text
TextPart
```

如果Agent有稳定结构化数据，可同时提供：

```text
DataPart
```

顶层公共结果应保持稳定，不直接暴露内部子Agent全部私有字段。

建议支持：

```text
status
answer
result_type
data
actions
error_code
retryable
agent_name
agent_version
```

具体Schema可以按业务扩展，但公共基础字段需要稳定。

---

# 二十四、宿主动作与业务能力分离

类似：

```text
open page
jump
handoff
download
approve
```

如果依赖特定宿主UI或协议，不能直接伪装成通用Agent Capability。

必须：

```text
有通用Action Contract
→ 才作为结构化action返回

没有
→ 降级成文本
```

v0.1 不强制定义通用Action Contract。

---

# 二十五、内部多智能体完全透明

公共合同禁止要求披露：

- 子Agent数量；
- 子Agent名称；
- 内部路由；
- 内部Tool；
- Prompt；
- Memory实现；
- Knowledge实现；
- 框架名称。

Agent内部可以随意变化，只要公共合同保持兼容。

---

# 二十六、版本变化规则

以下变化一般需要新公共Contract Revision：

- 公共能力减少或破坏性改变；
- Context Requirement增强；
- 身份语义改变；
- 协议版本改变；
- 结果字段破坏性改变；
- Resume/Cancel语义改变；
- 安全合同改变。

以下内部变化一般不要求公共Revision改变：

- Prompt优化；
- 内部Tool重构；
- 子Agent拆分；
- 模型更换；
- 数据库实现变化；

前提是公共行为合同没有破坏。

---

# 二十七、机器可读合同建议结构

示例只表达语义，不作为最终Schema代码：

```json
{
  "contract_version": "0.1",
  "agent": {
    "id": "example-agent",
    "display_name": "示例智能体",
    "version": "1.0.0"
  },
  "capabilities": [],
  "invocation_context": [],
  "interaction": {
    "streaming_transport": true,
    "incremental_content": false,
    "input_required": true,
    "resume": true,
    "cancel": false,
    "durable_task_recovery": false
  },
  "result_contract": {}
}
```

最终Schema必须由真实第一批实施结果再冻结，避免现在过早把字段写死。

---

# 二十八、任何Agent接入SnowHarness前的必备产物

至少：

```text
1. 标准AgentCard
2. 机器可读Agent Contract
3. Contract Test
4. Runtime Endpoint说明
5. Authentication说明
6. SnowHarness注册说明
```

不得要求：

```text
源码ZIP
Git仓库
framework
sourceRoot
commit
```

---

# 二十九、未来Codex Skill的职责

通用Skill以后在“Agent自己的仓库”中运行。

它可以读取源码。

工作流：

```text
读取真实源码
→ 找到真正用户入口
→ 找到能力范围
→ 找到隐含Context需求
→ 找到身份模型
→ 找到Session
→ 找到A2A/其他协议
→ 找到Result
→ 找到input-required/resume/cancel
→ 判断每项能力是声明、验证还是评测
→ 生成公共合同
→ 补齐Provider
→ 生成Contract Test
→ 生成SnowHarness注册资料
```

Skill不得：

- 把Tool直接翻译成Capability；
- 把内部Request Model直接复制成Public Contract；
- 仅看到cancel函数就宣称cancel；
- 仅看到SSE就宣称增量内容；
- 暴露Secret；
- 把内部子Agent拓扑写进SnowHarness注册资料。

---

# 三十、Skill的标准输出

未来每个Agent仓库统一生成：

```text
docs/agent-contract/
├─ agent-contract.md
├─ agent-contract.json
├─ capability-manifest.md
├─ invocation-context-contract.md
├─ conformance-report.md
└─ snowharness-registration.md
```

如果项目使用A2A，还应保证：

```text
/.well-known/agent-card.json
/.well-known/agent-contract.json
```

运行时真实可读取。

---

# 三十一、v0.1升级为正式规范的条件

至少完成：

1. 一个真实多Agent项目完成契约化；
2. 顶层Agent以黑盒方式被SnowHarness注册；
3. SnowHarness不读取其源码；
4. Capability展示正确；
5. Context Enrichment真实工作；
6. input-required/resume真实工作；
7. streaming真实工作；
8. cancel能力按真实证据声明；
9. Result Contract稳定；
10. Contract Test全部通过；
11. 第二个不同类型Agent使用同一规范时不需要改核心模型。

完成后：

```text
v0.1 Draft
→ v1.0
→ Codex Skill
```

---

# 三十二、当前草案最重要的架构红线

```text
Agent不是Tool
```

```text
SnowHarness负责上下文富化
Agent负责任务理解与业务补参
```

```text
Agent声明想要数据
不等于平台授权发送数据
```

```text
协议能力必须通过真实行为验证
```

```text
内部多Agent拓扑不是公共合同
```

```text
契约生成器可以看源码
SnowHarness永远不依赖源码
```
