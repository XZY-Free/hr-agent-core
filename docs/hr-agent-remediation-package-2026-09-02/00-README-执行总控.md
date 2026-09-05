# HR Agent 业务迁移整改工程包（不含“假实现”整改）

> 审查基线：`XZY-Free/hr-agent-core` `main`，commit `72bb3b6a7216b32a6a382e2faeae036ea7a67ee1`  
> 生成日期：2026-09-02  
> 实施仓库：**仅 `hr-agent-core`**  
> 本工程包定位：**直接实施说明，不是二次审查任务，也不是设计讨论稿。**

---

> **当前执行口径（2026-09-05 更新，优先于本包旧口径）**
> 测试验收环境已切换为 **AgentKit 远端 HTTP 客户端验收**：默认 `testpaths=["tests/agentkit"]`，`uv run pytest -q` 只收集该目录下用例，不装配本地业务 Agent、不自动读取本地配置文件；凭据由执行测试的进程环境安全注入。
> 已在授权边界内**完成全部 WP 验收**：全量 `tests/agentkit` 远端用例 258 passed / 0 failed / 0 skipped（耗时 925.86 秒），JUnit 证据 `tests/e2e/logs/agentkit-remediation-final-v33-v14-v11-2026-09-05.xml`；WP01-WP07 在授权边界内 PASS，整体结论 **业务迁移非假实现整改：PASS（AgentKit 开发环境；Gaia 为授权 stub 边界）**。
> **Gaia 保留（用户明确授权的唯一显式假数据例外）**：`GAIA_BACKEND=stub`、`EMPLOYEE_DATA_BACKEND=stub`、`GAIA_DRY_RUN=true`；真实 Gaia 接入与 OAuth 缓存未验证、不计为已通过，不再索取 Gaia 凭据。云端已发布并生效：`GAIA_BACKEND=stub` 且干跑时 `gaia_server_config_from_env` 不再强制 Gaia 四项（默认 `gaia` 仍校验）。服务端可信身份（`EMPLOYEE_IDENTITY_MAP_JSON` / `EMPLOYEE_REF_SECRET`）为真实必需配置、非 Gaia 例外。WP07 旧 L1-L5 本地 stub 验收层已被用户覆盖为**云部署服务验收**。
> 结论以真实远端证据为准；例外项（真实 Gaia/OAuth、Leave 下游 dry-run、附件外部 resolver、A2A cancel）明确列出、不虚化为已通过。下文业务矩阵、七 WP 顺序与冻结边界不变。

---

## 1. 为什么有这套工程包

当前 HR Agent 从 FastGPT 工作流迁移到 `Orchestrator + Leave + Consult + Employee Data + Domain Rules + A2A` 的总体方向是正确的。

整改目标不是把旧 FastGPT 的节点、快捷流、变量更新节点重新复制回来，而是把旧流程里真正属于业务的东西，以智能体架构应有的方式重新落稳：

- 模型负责理解用户表达、自然对话、补充信息与解释；
- 会话状态负责维护“正在办理的业务草稿”；
- 确定性领域规则负责类型、日期、排班、时长、权限、余额等交易事实；
- Gaia 只由服务端可信身份和服务端凭据访问；
- 本人数据、制度咨询、量化计算由职责清晰的 Agent / Domain Service 承担；
- A2A 负责跨 Agent 调用，不再承担一套越来越复杂的自然语言工作流。

本包处理的是上一轮审计中确认的**非“假实现”问题**。

---

## 2. 本轮明确排除的事项

下列问题已经确认存在，但**本轮不整改、不顺手修改、不设计替代方案**：

1. `page_jump` 等业务动作目前只在 Agent 内“说已经打开”，而没有像旧系统一样稳定返回后端可消费的业务 JSON；
2. `handoff` / “已转接人工”只有话术，没有真实后端动作；
3. 请假最终 `leave_support` 业务 JSON 在公共结果中的稳定输出，以及当前 dry-run 与“已提交”话术之间的假实现问题；
4. 撤回/销假等依赖前端/后端业务动作的 JSON 契约问题；
5. 其他同类“回复声称执行了某动作，但后端没有收到真实业务动作结果”的问题。

**实施 AI 不得在本工程包执行过程中修改上述行为。**

特别注意：

- 本轮允许修改 `apps/orchestrator/local_leave/submit.py` 内部的**校验、规则和数据计算**；
- 但不得在本轮改变它最终 dry-run / 提交结果对外表达的业务动作契约；
- 不得把“顺手把 page_jump/handoff 也做了”当作额外优化。

---

## 3. 本轮必须解决的七类根问题

### WP-01：Leave 身份与 Gaia 执行上下文断裂

当前：

`ExecutionSubject -> internal_user_id` 已有；

Employee Data 又有：

`internal_user_id -> employee_id` 的可信服务端映射；

但 Leave 仍从 ADK session state 读取：

- `employeeId`
- `corp_id`
- `client_secret`
- `grant_type`

公共 SnowHarness / A2A 入口既不允许调用方传这些字段，也没有把它们服务端注入 Leave，因此身份链没有闭环。

详见：`01-身份与Gaia执行上下文整改.md`

### WP-02：Leave 仍不是可靠的确定性领域引擎

当前主要问题包括：

- 所有假期一律先做“休息日拒绝”，与连续自然日假期规则冲突；
- `leave_days` 由模型传入，工具没有重新计算权威时长；
- 小时制请假被“float 天数”模型压扁；
- 排班未知被当成工作日；
- 跳休时只查用户原来的日期范围，不保证覆盖实际需要的后续工作日；
- `>27天` 的旧工作流技术限制被保留成领域规则；
- 缺理由时 Prompt 擅自写“个人事务”；
- 多假种冲突、离散日期的工作日连续性没有形成稳定领域校验；
- 多轮修改没有显式草稿状态和依赖字段失效机制；
- `input_required` 仍靠自然语言问号/关键词猜。

详见：`02-请假状态模型与确定性规则引擎整改.md`

### WP-03：Employee Data 拆分后能力缩水

当前独立 Employee Data 只稳定覆盖：

- 年休假余额；
- 医疗期；
- 工龄；
- 年假折算。

但旧系统本人数据能力包含多种假期余额。尤其：

- “我还有几天育儿假？”
- “我的调休还剩多少？”
- “我的假期余额有哪些？”

不能被简化成“年休假余额”或误判成制度咨询。

详见：`03-本人数据能力恢复整改.md`

### WP-04：旧咨询体系中的考勤量化计算能力丢失

当前 Consult Agent 只有：

- `kb_search`
- `parse_document`

但旧系统存在明确的：

- 迟到金额计算；
- 早退金额计算；
- 严重迟到/早退对应旷工天数计算；
- 多次记录累计；
- 10 分钟内月度前两次豁免等规则。

这些不应该重新做成 LLM 算术，也不能只做 RAG。

详见：`04-考勤量化计算能力整改.md`

### WP-05：A2A 路由重新退化成正则工作流

当前 `DeterministicRouteTable` 用 `_LEAVE_ACTION`、`_EMPLOYEE_DATA` 等正则直接决定业务域，未命中默认 Consult。

目标是：

**确定性层只负责 continuation / 安全 / 明确控制条件；普通业务语义交给受约束的结构化语义路由器。**

详见：`05-语义路由与会话续接整改.md`

### WP-06：公共附件合同接受了引用，但实际消费链不完整

公共请求已经接受 `attachment_references`，但 Local Runner / Remote Consult 的实际消费链不完整，opaque attachment reference 没有解析责任方，可能形成“请求合法，但附件被静默忽略”。

目标是：**在 hr-agent-core 内做到“能解析则安全解析，不能解析则明确失败，绝不静默忽略”。**

详见：`06-公共上下文与附件适配整改.md`

### WP-07：现有测试不能证明生产拓扑的业务迁移正确

当前兼容 eval 和 protocol-only test 不能证明真实的：

```text
Public A2A -> Router -> Local Leave / Remote Consult / Remote Employee Data
```

业务链。

必须建立生产拓扑 Golden Suite。

详见：`07-生产拓扑测试与业务验收整改.md`

---

## 4. 强制实施顺序

不得随意换顺序。

```text
WP-01 身份与 Gaia 上下文
        ↓
WP-02 Leave 状态与规则
        ↓
WP-03 Employee Data 能力恢复
        ↓
WP-04 Consult 考勤计算
        ↓
WP-05 语义路由与 continuation
        ↓
WP-06 公共上下文与附件
        ↓
WP-07 生产拓扑验收
```

说明：

- WP-03 与 WP-04 在代码依赖上部分可并行，但执行 AI **仍按上述顺序实施**，降低上下文分叉；
- WP-05 必须在各 Agent 的最终职责已经确定后再改；
- WP-07 不是最后才开始写测试，而是每个 WP 都同步补单元/集成测试，最后 WP-07 再建立总体验收门禁。

---

## 5. 架构冻结项

本轮整改后仍保持：

```text
hr-orchestrator
├── 本地 Leave Agent
├── 本地通用入口能力
├── A2A -> Consult Agent
└── A2A -> Employee Data Agent
```

不得：

- 把三个 Agent 重新合回一个超大 Agent；
- 把 Consult / Employee Data 改回本地生产 fallback；
- 修改 SnowHarness；
- 复制 FastGPT 的快捷/非快捷工作流节点结构；
- 把业务规则重新塞回 Prompt；
- 为了“方便”允许前端传 `employee_id`、`corp_id`、`client_secret`；
- 新增另一个与现有身份体系并行的身份映射机制；
- 新增一套和 `packages/hr_domain` 平行的 HR 规则目录；
- 在完成整改前把 README 写成“已完全迁移”“全部收口”。

---

## 6. 统一设计原则

### 6.1 模型理解不是交易事实

模型可以判断：

- 用户说的是年假；
- “明天下午”是什么意思；
- 用户想修改之前的日期；
- 用户是在问政策还是本人余额。

模型不能作为最终权威来源决定：

- employee_id；
- Gaia 凭据；
- 假期 typeCode；
- 是否有权限；
- 是否性别匹配；
- 某天是不是工作日；
- 权威 start/end time；
- 权威 leave duration；
- 余额是否充足；
- 迟到应扣多少钱；
- 是否记旷工；
- 业务字段是否允许凭空补“个人事务”。

### 6.2 所有交易字段必须可追溯

Leave Draft 中关键字段必须明确来源：

- `user`
- `normalized_user`
- `schedule`
- `rule`
- `system`

禁止使用无法说明来源的模型补值。

### 6.3 “未知”不能等于“工作日”“0”“默认值”

必须区分：

- 已知工作日；
- 已知休息日；
- 未查到排班 / 排班未知。

同样：

- 未知余额不能当 0；
- 未知单位不能默认天；
- 未知员工不能使用 user_id 代替；
- 未知半天边界不能自己取时间中点。

### 6.4 不用旧工作流的技术限制冒充业务规则

典型例子：

- `>27 天`；
- 固定只看 30/60 天排班；
- 快捷/非快捷分流；
- 大量“判断器#xx”；
- 用具体文案判断状态。

这些属于 FastGPT 实现限制，不应该原样进入新领域模型。

---

## 7. 完成定义

只有同时满足以下条件，本工程包才允许标记完成：

1. 公共 A2A 下 Leave 可通过可信主体得到 employee identity，且调用方不传 HR 主键/凭据；
2. Leave 关键业务事实由领域规则计算，不再信任 LLM 提供的 `leave_days`；
3. 连续假/跳休假正确区分；
4. 排班未知不再被当作工作日；
5. 小时制和天制不混算；
6. 多假种、日期连续性、半天、夜班、多轮改单有确定性测试；
7. Employee Data 恢复多假种本人余额；
8. 育儿假本人余额与育儿假地区政策不会互相误路由；
9. 迟到/早退量化计算由确定性工具完成；
10. 自然语言业务路由不再依赖不断增长的业务关键词正则；
11. `input_required` 不再靠回答文本中的问号和关键词猜；
12. 公共附件不能被静默忽略；
13. 生产拓扑 Golden Suite 通过；
14. 本轮明确排除的“假实现”行为未被偷偷改动；
15. README / 架构说明只在真实测试通过后更新为准确状态。

> 执行口径：上述条件按**当前 AgentKit 远端验收**逐 WP 收敛，且以真实证据对齐为准；Gaia 为授权 stub 例外。当前已完成 WP01-WP07 授权边界内验收（258/258，见本包当前执行口径）。

---

## 8. 实施 AI 的工作方式

实施 AI 必须：

- 先读本文件；
- 再按顺序只读当前 WP 文档；
- 直接实施；
- 不重新审查整个项目；
- 不输出替代架构提案；
- 不问“是否要这么做”；
- 不把文档中的 REQUIRED 改成“建议”；
- 不新增超出工程包的“顺手优化”。

具体执行口令见：

`09-Codex直接执行指令.md`
