# HR Agent 多智能体拆分、独立部署与 A2A 接入实施方案

> 文档用途：直接交给本地 Codex 作为实施约束与验收依据。
>
> 文档粒度：明确改造对象、职责边界、目录归属、迁移顺序、调用契约、失败语义、测试与验收；不提供具体函数实现和代码片段。
>
> 基线日期：2026-08-08。

---

## 1. 本方案要解决的问题

当前 `hr-agent` 已部署为一个 AgentKit Runtime，内部包含：

```text
root_agent
├── leave_agent
└── consult_agent
```

当前两个子 Agent 是同一 Python 进程内的 ADK 子 Agent：

- 共用同一套依赖、入口与 Runtime；
- 通过进程内 transfer 调用；
- 没有独立部署、独立版本、独立扩缩容和独立故障边界；
- 没有经过 AgentKit A2A 中心、AgentCard、A2A 智能体空间或语义发现；
- 无法完整体验 AgentKit 的多 Agent 注册、发现、调用、版本和跨 Runtime 观测能力。

本方案的目标不是机械地把每个函数都变成远程 Agent，而是把真正具有独立业务职责的能力拆成可独立部署的 Agent，同时保留确定性业务函数和外部接口为 Tool、MCP 或领域服务。

---

## 2. 冻结结论：本地 Codex 不得自行更改

### 2.1 最终目标角色

最终目标固定为四个业务角色：

| 目标角色 | 固定名称 | 是否独立 Runtime | 本轮实施状态 |
|---|---|---:|---|
| 人力入口与编排 | `hr-orchestrator` | 是 | 必须完成 |
| 人力制度咨询 | `hr-consult-agent` | 是 | 必须完成 |
| 员工本人数据查询 | `hr-employee-data-agent` | 是 | 必须完成 |
| 请假办理 | `hr-leave-agent` | 是 | 本轮只完成可拆分准备；满足门禁后另行拆分 |

### 2.2 本轮允许形成的运行拓扑

本轮完成后的正式拓扑固定为：

```text
业务前端/业务后端
        │
        ▼
hr-orchestrator Runtime
├── 本地页面跳转与固定交互工具
├── 本地 leave_agent（暂时保留）
├── A2A → hr-consult-agent Runtime
└── A2A → hr-employee-data-agent Runtime
```

本轮不得把 `leave_agent` 直接远程化。只有第 18 章列出的全部门禁通过并由用户再次确认后，才允许执行请假 Agent 独立部署。

### 2.3 不得拆成 Agent 的对象

以下对象必须继续保持 Tool、普通领域函数、共享基础设施或平台资源，禁止为了体验 A2A 包装成 Agent：

- `page_jump`；
- `calc_end_date`；
- `split_year_quota`；
- `LeaveForm`；
- 工具统一返回结构；
- 假期类型、性别限制、页面码表等常量；
- 盖亚 HTTP 客户端；
- Viking/AgentKit Knowledge 检索客户端；
- JWT 获取与缓存；
- 单个盖亚查询接口；
- 单个知识库 collection；
- 固定话术。

### 2.4 命名红线

禁止创建以下版本式或过渡式长期命名：

```text
v2/
v3/
new_agent/
new_consult/
legacy/
temp_agent/
a2a_v1/
```

目录和类型必须按长期领域职责命名。版本只存在于 AgentKit Runtime 版本、A2A Agent 版本、Skill 版本、发布记录和 Git 提交中，不进入长期模块名称。

### 2.5 不允许永久双轨

迁移期间允许为验证保留有限期 `local/a2a` 切换，但必须满足：

1. 双轨只用于迁移验证；
2. 每一条双轨都有删除任务；
3. A2A 验收完成后，删除咨询和员工数据的本地子 Agent 调用路径；
4. 最终代码不得长期保留“旧本地实现 + 新远程实现”两套编排入口；
5. 共享的领域函数和工具客户端可以复用，不视为双轨。

迁移期只允许使用以下两个明确开关：

| 开关 | 允许值 | 用途 |
|---|---|---|
| `HR_CONSULT_TRANSPORT` | `local` / `a2a` | 咨询能力迁移验证 |
| `HR_EMPLOYEE_DATA_TRANSPORT` | `local` / `a2a` | 本人数据能力迁移验证 |

不得创建含义重叠的其他开关。完成第14章批次7后，两个开关及`local`分支必须从正式代码、部署配置和文档中删除。

### 2.6 三类名称必须严格区分

ADK内部Agent名称可能受标识符规则约束，不能与云资源展示名混用。命名矩阵固定为：

| 角色 | ADK内部 `name` | A2A注册名 | 开发Runtime名 |
|---|---|---|---|
| 编排 | `hr_orchestrator` | 本轮不作为被调A2A Agent注册 | `hr-orchestrator-dev` |
| 咨询 | `hr_consult_agent` | `hr-consult-agent` | `hr-consult-agent-dev` |
| 本人数据 | `hr_employee_data_agent` | `hr-employee-data-agent` | `hr-employee-data-agent-dev` |
| 请假 | `hr_leave_agent` | `hr-leave-agent` | `hr-leave-agent-dev`，本轮不创建 |

所有ADK协议路径、`app_name`、本地客户端、测试夹具和会话资源使用内部名称`hr_orchestrator`等；AgentKit控制台资源、A2A空间和部署文档使用带连字符的资源名。不得在同一字段中交叉使用。

---

## 3. 当前代码事实基线

本地 Codex 开工前必须重新核对当前工作区，以下事实与实际代码冲突时必须停止并报告，不得自行选择一套理解继续实施。

### 3.1 当前入口

- 服务入口：`agent.py`；
- AgentKit 应用：`AgentkitAgentServerApp`；
- 当前根 Agent：`root_agent`；
- 当前短期记忆：`ShortTermMemory(backend="local")`；
- 当前接口：ADK 会话接口、`/run_sse` 以及 AgentKit 兼容调用入口；
- 当前业务变量：`employeeId`、`corp_id`、`client_secret`、`grant_type` 通过 `session.state` 注入。

### 3.2 当前职责

| 当前模块 | 当前职责 |
|---|---|
| `main_agent.py` | 总入口、意图分流、查询、页面跳转、转人工话术 |
| `consult_agent.py` | 制度咨询、文档问答、本人数据兜底查询 |
| `leave_agent.py` | 请假信息收集、确认、校验与请假单生成 |
| `tools/gaia` | 盖亚认证、余额、权限、排班、员工信息、提交骨架 |
| `tools/rules` | 年假计算、日期计算、知识检索、文档解析、页面跳转 |
| `knowledge` | 本地 Stub 与 AgentKit/Viking 检索后端 |
| `callbacks` | 页面跳转标记注入 |

### 3.3 当前部署与依赖

- Python 3.12；
- AgentKit Basic App；
- 云端地域：北京；
- Runtime 鉴权：`key_auth`；
- `agentkit-sdk-python==0.5.10`；
- `veadk-python==0.5.37`；
- `google-adk==1.32.0`；
- 当前官方稳定基线参考：AgentKit SDK 0.8.1、veADK 1.1.0。

### 3.4 当前评测事实

当前 `tests/eval/cases.yaml` 实际包含 21 条用例，不是文档中曾记录的 22 条。迁移不得减少这 21 条用例的覆盖范围。

---

## 4. 目标架构

### 4.1 目标逻辑架构

```text
┌──────────────────────────────────────────────────────────┐
│                    HR Orchestrator                       │
│                                                          │
│  入口鉴权 / 会话关联 / 意图判断 / A2A 调度 / 结果汇总     │
│  页面跳转 / 取消请假引导 / 人工服务入口 / 闲聊             │
└───────────────┬──────────────────┬───────────────────────┘
                │                  │
           A2A 调用           A2A 调用
                │                  │
                ▼                  ▼
┌────────────────────────┐  ┌─────────────────────────────┐
│ HR Consult Agent       │  │ HR Employee Data Agent      │
│                        │  │                             │
│ 制度/政策/操作/文档问答 │  │ 余额/医疗期/年假折算/本人数据 │
│ Knowledge / 文档解析    │  │ 只读 Gaia 查询              │
└────────────────────────┘  └─────────────────────────────┘

                hr-orchestrator 内暂时保留
                ┌─────────────────────────────┐
                │ Local Leave Agent           │
                │ 多轮槽位 / 确认 / 校验 / 表单 │
                └─────────────────────────────┘
```

### 4.2 最终目标架构

在会话、身份和交易契约门禁通过后，`hr-leave-agent` 才从编排 Runtime 中拆出：

```text
hr-orchestrator
├── A2A → hr-consult-agent
├── A2A → hr-employee-data-agent
└── A2A → hr-leave-agent
```

最终 `hr-orchestrator` 不再承载知识库查询、本人数据查询或请假校验逻辑，只负责入口、编排、前端交互和统一故障处理。

---

## 5. Agent 职责冻结

### 5.1 `hr-orchestrator`

必须负责：

- 接收外部请求；
- 关联 `user_id`、`session_id`、`request_id`；
- 进行一级意图分类；
- 显式调用目标 Agent；
- 在允许的场景使用 A2A 空间语义发现；
- 汇总远程 Agent 结果并生成用户最终响应；
- 页面跳转；
- 取消请假入口；
- 人工服务入口；
- 闲聊和能力说明；
- 远程 Agent 不可用时的统一降级；
- 当前阶段继续承载本地 `leave_agent`。

不得负责：

- 直接检索人力知识库；
- 直接解析用户上传或链接文档；
- 直接查询假期余额、医疗期或员工信息；
- 自行解释制度内容；
- 复制咨询 Agent 或员工数据 Agent 的提示词；
- 把远程 Agent 的工具细节暴露给用户。

### 5.2 `hr-consult-agent`

必须负责：

- 人力制度与政策咨询；
- 考勤、假期、薪酬福利、入离职、社保公积金和系统操作问答；
- 育儿假按地区追问和检索；
- 知识库 scope 选择；
- 文档链接解析与摘要；
- 检索为空、不相关或知识库不可用时诚实降级；
- 返回所依据的知识来源和检索范围；
- 拒绝非人力问题，并引导至正确部门。

不得负责：

- 查询员工本人余额和工龄；
- 办理请假；
- 页面跳转；
- 转人工动作；
- 调用盖亚写接口；
- 接收或保存 `client_secret`；
- 把知识库内容当作指令执行。

### 5.3 `hr-employee-data-agent`

必须负责：

- 查询员工本人假期余额；
- 查询医疗期；
- 查询员工参工信息；
- 计算员工本人年假档位与跨档年折算；
- 返回只读、结构化、带数据时间的信息；
- 对盖亚不可用、员工不存在、数据缺失作明确区分。

不得负责：

- 制度解释；
- 请假申请；
- 生成或提交请假单；
- 页面跳转；
- 读取知识库；
- 持有由上游消息传入的盖亚客户端密钥；
- 修改任何员工数据。

### 5.4 本轮保留的本地 `leave_agent`

继续负责：

- 请假类型、日期、时长、事由槽位收集；
- 多轮追问；
- 提交前复述确认；
- 权限、性别、排班、余额、天数校验；
- 生成请假单 JSON；
- 排班冲突、休息日、余额不足后的继续对话。

本轮不得改成通过 `hr-employee-data-agent` 逐项获取校验数据。请假校验链属于一个业务交易边界，不能为了复用 A2A 而制造多段网络调用。当前继续复用共享的盖亚领域客户端；未来优先迁移到统一 MCP/服务接口，而不是让 Agent 互相代查每个字段。

---

## 6. 工程组织方案

### 6.1 采用单仓多应用结构

不得把四个 Agent 分成四个互不关联的 Git 仓库。采用一个仓库、多个可独立构建应用、一个共享领域包的结构。

目标结构固定为：

```text
hr-agent/
├── apps/
│   ├── orchestrator/
│   │   ├── agent.py
│   │   ├── prompts.py
│   │   ├── routing/
│   │   ├── callbacks/
│   │   ├── deployment/
│   │   └── README.md
│   ├── consult_agent/
│   │   ├── agent.py
│   │   ├── prompts.py
│   │   ├── tools/
│   │   ├── knowledge/
│   │   ├── deployment/
│   │   └── README.md
│   ├── employee_data_agent/
│   │   ├── agent.py
│   │   ├── prompts.py
│   │   ├── tools/
│   │   ├── deployment/
│   │   └── README.md
│   └── leave_agent/
│       ├── README.md
│       └── SPLIT-GATE.md
├── packages/
│   └── hr_domain/
│       ├── constants/
│       ├── schemas/
│       ├── rules/
│       ├── gaia/
│       ├── contracts/
│       └── errors/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── eval/
│   ├── integration/
│   └── e2e/
├── deployment/
│   ├── README.md
│   ├── resource-inventory.example.yaml
│   └── environments/
│       ├── dev/
│       ├── staging/
│       └── prod/
├── pyproject.toml
├── uv.lock
└── README.md
```

### 6.2 共享包允许包含的内容

`packages/hr_domain` 只允许包含与 Agent 运行框架无关的稳定资产：

- 假期类型与编码；
- 性别限制；
- 休息日规则；
- 页面码表中被多个模块引用的纯数据；
- Pydantic 业务 Schema；
- 工具结果和领域错误模型；
- 年假折算；
- 请假日期推算；
- 盖亚请求与响应适配；
- JWT 客户端与缓存策略；
- A2A 结构化结果契约；
- 时间、请求标识等通用领域辅助逻辑。

### 6.3 共享包禁止包含的内容

- 已实例化 Agent；
- Agent 提示词；
- `sub_agents` 装配；
- Runtime 入口；
- 某个应用的 AgentKit 配置；
- 应用专属环境变量读取；
- A2A 路由决策；
- 页面跳转回调；
- 直接依赖某个应用目录的导入。

### 6.4 应用之间的导入红线

- `orchestrator` 禁止导入 `consult_agent` 的 Agent 实例；
- `orchestrator` 禁止导入 `employee_data_agent` 的 Agent 实例；
- 两个独立 Agent 应用禁止相互导入；
- 应用只允许依赖 `hr_domain`；
- A2A 调用只能通过远程协议或 AgentKit A2A 资源完成；
- 测试不得通过直接导入远端 Agent 来伪造 A2A 集成成功。

---

## 7. 依赖升级与兼容性门禁

### 7.1 升级目标

为对齐当前 AgentKit A2A、会话资源、Skill 和观测能力，本次拆分使用以下明确目标版本：

- `agentkit-sdk-python==0.8.1`；
- `veadk-python==1.1.0`。

`google-adk` 不得由本地 Codex随意选择版本。处理规则固定为：

1. 先读取上述两个目标包声明的依赖范围；
2. 如果二者能共同解析，则使用解析出的同一 `google-adk` 版本并写入锁文件；
3. 如果项目必须显式锁定，则锁定为两个目标包共同支持的最高稳定版本；
4. 如果不存在共同支持版本，立即停止升级并输出冲突依赖链，不得降级目标包或使用预发布版本；
5. 不得使用 `--no-deps`、强制覆盖或删除锁文件规避冲突。

### 7.2 升级前必须建立行为基线

升级前必须：

- 执行全部非评测单元测试；
- 执行当前 21 条对话评测；
- 保存每条用例的工具调用、最终回答、耗时与错误；
- 记录本地多轮会话行为；
- 记录当前知识检索返回的 `content/source/score`；
- 记录当前 JUMP 标记行为；
- 记录当前部署入口和 SSE 事件结构。

无法获得真实模型或真实知识库凭据时，必须分别使用现有 Stub 完成结构基线，并把未执行项列为外部门禁，不得声称完成真实回归。

### 7.3 私有 SDK 字段清理

当前知识库后端使用 veADK 内部私有字段获取底层 Viking 客户端。目标实现不得继续依赖以下类型的私有成员：

- 以下划线开头的后端对象；
- 以下划线开头的 SDK 客户端；
- 未进入官方公开契约的内部调用方法。

必须改用官方公开接口。若公开接口无法同时保留 `content/source/score`：

1. 不得静默丢失字段；
2. 不得伪造 score；
3. 必须停止并提交能力差异报告；
4. 由用户决定是接受字段降级还是直接使用 Viking 官方公开 SDK。

---

## 8. A2A 智能体与空间规划

### 8.1 A2A 空间

必须按环境创建独立空间：

| 环境 | 空间名称 | 语义检索 |
|---|---|---|
| 开发 | `hr-agents-dev` | 初始关闭，完成显式调用后开启 |
| 预发布 | `hr-agents-staging` | 开启 |
| 生产 | `hr-agents-prod` | 本轮不得创建，除非用户单独批准 |

禁止开发、预发布和生产共用一个 A2A 空间。

### 8.2 A2A Agent 注册名称

| Agent | 注册名称 | 默认说明 |
|---|---|---|
| 咨询 | `hr-consult-agent` | 回答人力制度、政策、薪酬福利、系统操作和文档内容问题 |
| 员工数据 | `hr-employee-data-agent` | 查询当前员工本人假期余额、医疗期、工龄与年假折算，只读 |
| 请假 | `hr-leave-agent` | 收集、校验并生成请假申请；本轮不注册 |

### 8.3 AgentCard 技能定义

`hr-consult-agent` 至少声明以下稳定技能：

| Skill ID | 用途 |
|---|---|
| `hr-policy-consultation` | 人力制度与政策问答 |
| `hr-benefit-consultation` | 薪酬福利与职级相关问答 |
| `hr-system-operation-guide` | 人事系统操作手册问答 |
| `hr-document-question-answering` | 基于文档链接的解析和问答 |

`hr-employee-data-agent` 至少声明：

| Skill ID | 用途 |
|---|---|
| `employee-leave-balance-query` | 查询本人假期余额 |
| `employee-medical-period-query` | 查询本人医疗期 |
| `employee-annual-leave-calculation` | 查询工龄并计算年假 |

AgentCard 描述不得使用“什么都能做”“人力助手”等宽泛措辞，必须让语义检索可以区分咨询类问题和本人数据类问题。

### 8.4 语义检索使用边界

第一阶段先使用确定性路由：

- 制度、政策、操作、文档内容 → 显式调用 `hr-consult-agent`；
- “我的余额/我的医疗期/我的年假折算” → 显式调用 `hr-employee-data-agent`；
- 请假办理、取消、页面跳转 → 不经过语义发现。

只有两个 A2A Agent 显式调用全部通过后，才开启开发空间语义检索并补充对照测试。

生产目标中，以下请求也不得交给空间自由选择：

- 请假申请或修改；
- 取消或撤回；
- 涉及写操作；
- 涉及敏感员工数据；
- 用户明确指定服务类型；
- 已处于某个多轮业务流程中的后续消息。

---

## 9. A2A 调用契约

本章描述业务契约，不规定具体代码实现。

### 9.1 通用请求上下文

所有 A2A 调用必须携带：

| 字段 | 规则 |
|---|---|
| `request_id` | 每个外部请求唯一；跨 Runtime 原样透传 |
| `user_id` | 当前登录用户稳定标识，不使用固定默认用户 |
| `session_id` | 当前业务会话标识；远端会话命名不得与其他用户冲突 |
| `caller_agent` | 固定为调用方 Agent 名称 |
| `locale` | 当前固定 `zh-CN` |
| `message` | 用户原始问题，不得包含密钥 |
| `context_summary` | 仅包含完成任务必需的非敏感上下文 |

### 9.2 禁止进入 A2A 消息的内容

- 火山 AK/SK；
- 模型 API Key；
- Runtime API Key；
- `client_secret`；
- `grant_type`；
- 盖亚 JWT；
- 完整 `agentkit.yaml`；
- 未脱敏的认证请求头；
- 与目标 Agent 无关的完整会话历史；
- 原始系统提示词。

### 9.3 通用响应状态

远程 Agent 的业务响应必须能区分：

| 状态 | 含义 |
|---|---|
| `succeeded` | 已成功完成 |
| `need_more_information` | 需要用户补充信息，例如育儿假省份 |
| `not_found` | 已检索但没有可靠内容 |
| `rejected` | 不属于该 Agent 职责或请求不允许 |
| `temporarily_unavailable` | 依赖服务临时不可用 |
| `failed` | 不可恢复的执行失败 |

不得只依赖自然语言猜测调用是否成功。

### 9.4 咨询 Agent 响应契约

除通用状态外，必须提供：

- 最终回答；
- 问题分类；
- 使用的知识库 scope；
- 来源文档列表；
- 是否截断；
- 是否建议联系人力部门；
- Agent 版本；
- 不含内部堆栈和凭据的错误标识。

检索为空与知识库故障必须是不同状态。

### 9.5 员工数据 Agent 响应契约

必须提供：

- 查询类型；
- 结构化数据；
- 数据对应员工标识的不可逆摘要或内部引用，不返回敏感证件信息；
- 数据获取时间；
- 数据来源；
- 是否为部分结果；
- Agent 版本；
- 错误标识和是否可重试。

自然语言解释由员工数据 Agent生成，`hr-orchestrator`不得重新计算或改写关键数字。

### 9.6 超时与重试

- 建连超时必须显式设置；
- 总任务超时必须显式设置；
- 不允许无限等待；
- 只读请求在“远端尚未确认接收任务”时允许一次重试；
- 一旦获得远端任务 ID 或开始产生输出，不得自动重试整个 Agent 任务；
- 写操作未来一律不得由编排 Agent自动重试；
- 超时必须返回统一的 `temporarily_unavailable`，并保留跨 Runtime `request_id`。

具体超时数值在首次基准测试后冻结，Codex不得根据个人经验随意填写。首次测试前使用 SDK 官方默认值并记录实际耗时分布。

---

## 10. 会话、身份与凭据处理

### 10.1 现状问题

当前 `ShortTermMemory(backend="local")` 是进程内存。Runtime 扩容、重启或请求落到其他实例后，多轮状态可能丢失。

### 10.2 本轮要求

本轮必须完成以下事实验证：

1. 导入或创建开发环境 AgentKit 会话资源；
2. `hr-orchestrator` 接入该会话资源；
3. 验证同一 `user_id + session_id` 在 Runtime 重启后仍能继续；
4. 验证两个实例之间的会话一致性；
5. 验证 `session.state` 中哪些字段会被观测、日志或事件保存；
6. 输出敏感字段可见性报告。

若会话资源接入因 SDK 或账号能力被阻塞，A2A 咨询和只读查询仍可继续，但不得拆分请假 Agent，也不得把 Orchestrator 扩容到多实例后宣称会话可靠。

### 10.3 凭据归属

调整后：

- `employeeId`：来自已验证的登录身份或受信任业务后端映射；
- `corp_id`：作为服务端租户配置，不由普通用户消息提供；
- `client_secret`：只存在于调用盖亚的 Runtime 凭据或安全环境配置中；
- `grant_type`：服务端固定配置；
- 盖亚 JWT：仅在服务端内存缓存，不进入 Agent 上下文；
- A2A 消息不得传递上述密钥。

### 10.4 过渡期身份规则

如果当前尚未接入企业 SSO：

- 外部业务后端继续作为受信任身份源；
- `employeeId` 只能由受信任后端注入；
- 禁止直接相信最终用户请求体中的 `employeeId`；
- Runtime API Key 只能证明调用方应用身份，不能证明员工身份；
- 文档必须明确“应用鉴权”和“员工身份”是两层不同概念。

---

## 11. 盖亚访问层调整

### 11.1 客户端归属

盖亚客户端移动到共享领域包，由以下应用复用：

- `hr-employee-data-agent`；
- 本轮仍位于 `hr-orchestrator` 的本地 `leave_agent`；
- 未来 `hr-leave-agent`。

### 11.2 JWT 缓存修正

当前每次 `from_state()` 新建 `GaiaClient`，导致实例内部 JWT 缓存难以跨工具调用复用。

目标行为必须是：

- 同一 Runtime、同一租户、同一环境复用有效 JWT；
- 生产与沙箱缓存隔离；
- 到期前刷新；
- 获取失败不缓存；
- 不在日志中输出 JWT 和 client secret；
- 并发刷新时避免重复向认证服务发起大量请求；
- 单元测试覆盖缓存命中、过期、环境隔离和失败重试。

### 11.3 MCP 后续边界

本轮不把盖亚接口同时重构为 MCP，以免“Agent拆分”和“工具协议迁移”叠加导致无法定位问题。

本轮只需保证共享盖亚访问层边界清楚。A2A 拆分验收后，再单独执行：

1. 先把余额、医疗期、员工信息等只读接口导入 AgentKit MCP Gateway；
2. 完成入站认证、工具集和工具监控；
3. 对比本地函数工具与 MCP 工具；
4. 最后决定请假校验链是否切换到 MCP。

---

## 12. 知识库与咨询 Agent 调整

### 12.1 知识库所有权

四个知识范围只由 `hr-consult-agent` 使用：

- `policy`；
- `handbook`；
- `salary`；
- `childcare`。

`hr-orchestrator` 和 `hr-employee-data-agent` 不得配置这些知识库连接。

### 12.2 检索错误语义

必须修正当前“单库异常被吞掉后整体返回空列表”的模糊行为：

- 某一库失败、其他库成功：返回部分成功并列出失败 scope；
- 指定单库失败：返回知识库不可用；
- 检索成功但无结果：返回 `not_found`；
- 检索成功但相关度不足：返回 `not_found`，不得拼凑回答；
- `all` 模式部分失败：不得把结果伪装成完整检索。

相关度阈值不得由 Codex主观决定。先记录现有真实知识库评测中的 score 分布，再由评测结果冻结阈值；阈值确定前只保留模型相关性判断和明确的低分观测字段。

### 12.3 已知知识质量问题必须保留为验证项

- 病假工资制度缺失；
- 加班调休可能召回育儿假；
- 婚假问题可能只召回一次性休完 FAQ；
- 部分查询 top1 不相关；
- 多数 score 偏低。

拆分成功不得以“Agent能回答”作为唯一标准，必须继续检查检索来源和得分。

---

## 13. 编排路由调整

### 13.1 一级路由表

`hr-orchestrator` 的路由优先级冻结为：

1. 请假申请、修改、补登或当前正在进行的请假多轮 → 本地 `leave_agent`；
2. 取消或撤回请假 → 页面跳转与固定引导；
3. 员工本人余额、医疗期、工龄、本人年假折算 → A2A `hr-employee-data-agent`；
4. 打开具体页面 → 本地 `page_jump`；
5. 人力制度、政策、薪酬福利、系统操作、文档内容 → A2A `hr-consult-agent`；
6. 明确要求人工或明显不满 → 人工服务入口；
7. 闲聊 → 本地简短回复。

### 13.2 多轮粘性

一旦进入一个业务流程，后续短消息如“确认”“改成后天”“那病假呢”必须优先回到当前流程，不得每轮重新做空间语义发现。

需要在会话状态中记录：

- 当前活动流程；
- 当前负责 Agent；
- 远端任务引用；
- 最后一次成功调用时间；
- 是否等待用户补充信息；
- 可安全保存的槽位摘要。

不得保存密钥。

### 13.3 远端失败降级

固定用户语义：

| 场景 | 用户侧行为 |
|---|---|
| 咨询 Agent超时 | 告知咨询服务暂时繁忙，建议稍后重试；不编造制度 |
| 知识库无结果 | 如实说明暂未查到，建议咨询人力部门 |
| 员工数据 Agent超时 | 告知本人数据暂时无法查询；不得给出历史或猜测数字 |
| A2A鉴权失败 | 对用户统一为服务暂不可用；内部记录鉴权错误 |
| A2A返回非法结构 | 不把原始内容直接展示；记录契约错误 |
| 远端拒绝职责 | 编排层只允许按冻结路由表重新路由一次，禁止循环转派 |

---

## 14. 实施批次

每一批必须独立提交、独立测试。不得把所有变化压成一个提交。

### 批次 0：快照、清理与事实冻结

目标：建立可回归的改造起点。

必须完成：

- 记录 Git HEAD 和工作区状态；
- 不覆盖用户现有未提交改动；
- 检查压缩包中 `.env`、`agentkit.yaml`、`.venv` 等不应进入版本库的内容；
- 确认 Git 历史未提交真实密钥；
- 如果密钥曾进入 Git，停止并报告，不擅自改写历史；
- 执行当前测试基线；
- 生成当前模块依赖图；
- 记录三个 Agent 的工具列表；
- 记录 21 条评测归属；
- 输出 `docs/current-baseline.md`。

验收：所有事实有文件或测试证据，不能仅根据旧文档推断。

### 批次 1：依赖升级与兼容性修复

目标：把工程升级到第 7 章冻结的目标版本，不改变业务职责。

必须完成：

- 更新依赖与锁文件；
- 修复 SDK 公开接口差异；
- 清理知识库私有成员依赖；
- 验证 AgentServerApp、会话、SSE、JUMP 回调；
- 重新执行完整测试；
- 对比升级前后工具调用和回答差异；
- 输出 `docs/sdk-upgrade-report.md`。

停止条件：依赖无法共同解析、官方公开接口不能满足必要契约、21条评测出现无法解释的系统性退化。

### 批次 2：单仓多应用重组，但保持单Runtime行为

目标：完成目录和依赖边界，为独立构建做准备，不先引入远程调用。

必须完成：

- 创建 `apps` 和 `packages/hr_domain`；
- 移动共享常量、Schema、规则、盖亚客户端；
- 把提示词归入各自应用；
- 为三个当前角色建立独立应用边界；
- 保持现有入口可运行；
- 禁止出现循环依赖；
- 更新所有测试路径；
- 更新根 README 架构说明。

验收：行为与批次1一致，且应用间不存在实例导入。

### 批次 3：独立咨询 Agent

目标：生成可独立运行和部署的 `hr-consult-agent`。

必须完成：

- 独立入口；
- 独立模型配置；
- 独立知识库配置；
- 独立工具列表；
- 独立 AgentCard；
- 独立健康检查；
- 独立单元、评测和契约测试；
- 独立部署说明；
- 本地 A2A 服务验证。

咨询 Agent不得依赖 Orchestrator 的 Python 模块或会话内存。

### 批次 4：独立员工数据 Agent

目标：生成只读的 `hr-employee-data-agent`。

必须完成：

- 独立入口；
- 独立只读工具列表；
- 盖亚凭据在目标 Runtime 内配置；
- 不从 A2A 请求接收 secret；
- 独立 AgentCard；
- 年假计算仍由共享领域规则完成；
- 数据时间、来源与错误分类；
- 独立测试和部署说明。

### 批次 5：Orchestrator 接入显式 A2A 调用

目标：先不依赖语义发现，完成稳定远程调用。

必须完成：

- 咨询路由改为显式调用远端咨询 Agent；
- 本人数据路由改为显式调用远端员工数据 Agent；
- 请求上下文透传；
- 结构化响应校验；
- 超时和错误降级；
- 跨 Runtime request ID；
- 双轨只作为测试开关存在；
- 端到端通过后删除生产路径中的本地咨询和本人数据调用。

### 批次 6：开发环境部署与A2A注册

执行云端写操作前，Codex必须暂停并列出：

- 将创建或更新的 Runtime；
- A2A 空间；
- A2A Agent；
- API Key/JWT 鉴权方式；
- 预计持续计费资源；
- 现有资源是否复用；
- 销毁命令与回滚方式。

用户确认后才允许：

1. 部署 `hr-consult-agent` 开发 Runtime；
2. 部署 `hr-employee-data-agent` 开发 Runtime；
3. 创建 `hr-agents-dev`；
4. 注册两个 Agent；
5. 部署或更新 `hr-orchestrator` 开发 Runtime；
6. 验证显式 A2A 调用；
7. 开启语义检索；
8. 验证语义发现；
9. 验证跨 Runtime Trace；
10. 记录资源清单，但不记录密钥值。

### 批次 7：删除迁移双轨并冻结第一阶段

必须完成：

- 删除 Orchestrator 内的咨询 Agent实例装配；
- 删除 Orchestrator 内的本人数据工具装配；
- 删除已经无调用方的旧提示词；
- 删除迁移开关；
- 保留领域共享代码；
- 更新架构文档、部署文档和资源清单；
- 运行全套回归；
- 输出第一阶段完成报告。

第一阶段只有完成本批次才算结束。

### 批次 8：请假 Agent 拆分准备，不执行远程切换

必须完成：

- 写清请假状态机；
- 定义槽位状态；
- 定义确认状态；
- 定义请假单 Artifact；
- 定义请求幂等键；
- 定义超时、重试、取消与结果不确定语义；
- 验证会话资源；
- 验证员工身份映射；
- 验证凭据不会通过 A2A 传播；
- 输出 `apps/leave_agent/SPLIT-GATE.md`。

本批次不得注册或切换 `hr-leave-agent`。

---

## 15. 测试重组

### 15.1 现有21条评测的固定归属

#### Orchestrator

- `page_jump_punch`；
- `cancel_leave`；
- `handoff`。

#### 本地 Leave Agent

- `quick_tomorrow`；
- `missing_type_asks`；
- `multi_type_rejected`；
- `gender_mismatch`；
- `rest_day`。

#### Employee Data Agent

- `balance_query`；
- `annual_calc`；
- `personal_data_not_kb`。

#### Consult Agent

- `consult_transfer`；
- `policy_late_fine`；
- `non_hr_rejected`；
- `childcare_sichuan`；
- `childcare_asks_province`；
- `salary_term_alias`；
- `kb_empty_honest`；
- `doc_qa`；
- `followup_present`；
- `policy_probation`。

### 15.2 新增单元测试

必须覆盖：

- Agent职责与工具装配；
- Agent间禁止实例导入；
- 路由优先级；
- 活动流程粘性；
- A2A请求字段过滤；
- 密钥不得进入请求；
- 响应状态解析；
- 检索空结果与故障区分；
- JWT缓存复用；
- 日期不得在进程启动时永久冻结；
- JUMP标记不受拆分影响。

### 15.3 新增契约测试

每个远端 Agent 必须有消费者/提供者契约测试，覆盖：

- 成功；
- 需要补充信息；
- 无结果；
- 职责拒绝；
- 暂时不可用；
- 非法结构；
- 未知字段兼容；
- 缺少必填字段；
- Agent版本字段；
- request ID透传；
- user/session隔离。

### 15.4 新增A2A端到端用例

至少包含：

| 输入 | 期望目标 |
|---|---|
| “迟到扣款制度是什么” | `hr-consult-agent` |
| “四川育儿假有几天” | `hr-consult-agent` |
| “我还有几天年假” | `hr-employee-data-agent` |
| “我的医疗期余额” | `hr-employee-data-agent` |
| “我的年假怎么折算” | `hr-employee-data-agent` |
| “明天请一天年假” | 本地 `leave_agent`，不得使用空间语义发现 |
| “打开打卡明细” | 本地 `page_jump` |
| “转人工” | 本地人工入口 |

### 15.5 失败注入

必须验证：

- 远端 Runtime关闭；
- A2A空间不可访问；
- 鉴权失败；
- 超时；
- 返回500；
- 返回空文本；
- 返回不符合契约的数据；
- Knowledge单库失败；
- Gaia认证失败；
- 会话不存在；
- 同一session并发请求；
- Runtime重启后继续会话。

---

## 16. 观测要求

### 16.1 跨 Runtime Trace

必须能从 Orchestrator 请求追踪到：

- 路由判断；
- A2A目标 Agent；
- 远端 Agent执行；
- 模型调用；
- Knowledge或Gaia工具调用；
- 最终响应；
- 错误与重试。

### 16.2 必须记录但不得泄密的字段

允许记录：

- request ID；
- 脱敏 user ID；
- session ID；
- 调用方和目标 Agent；
- Agent版本；
- 路由原因码；
- 状态；
- 耗时；
- Token；
- 工具名；
- Knowledge scope；
- 错误码。

禁止记录：

- 模型 Key；
- AK/SK；
- Runtime API Key；
- client secret；
- Gaia JWT；
- 完整认证头；
- 无必要的员工敏感信息。

### 16.3 拆分前后对比

必须比较：

- 整体P50/P95耗时；
- 新增A2A网络耗时；
- 每轮模型调用次数；
- Token；
- 工具调用次数；
- 错误率；
- 知识检索相关性；
- 远端故障时用户体验；
- 单Runtime与多Runtime资源成本。

没有基线数据时不得凭主观判断“拆分后更快”或“更稳定”。

---

## 17. 部署配置要求

### 17.1 每个应用独立配置

三个可部署应用必须各自拥有：

- 唯一 Agent 名；
- 唯一 Runtime 名；
- 独立入口；
- 独立健康检查；
- 独立环境变量清单；
- 独立依赖构建验证；
- 独立部署与销毁说明；
- 独立日志查询说明；
- 独立A2A注册说明。

### 17.2 建议开发资源名，Codex不得自行换名

| 资源 | 名称 |
|---|---|
| Orchestrator Runtime | `hr-orchestrator-dev` |
| Consult Runtime | `hr-consult-agent-dev` |
| Employee Data Runtime | `hr-employee-data-agent-dev` |
| A2A Space | `hr-agents-dev` |
| Consult A2A Agent | `hr-consult-agent` |
| Data A2A Agent | `hr-employee-data-agent` |

如果平台名称冲突，Codex必须暂停并报告现有同名资源，不得自动添加随机后缀。

### 17.3 配置文件安全

- 真实 `agentkit.yaml` 不进入Git；
- 提供去密的 `agentkit.example.yaml` 或等价说明；
- `.env` 不进入Git；
- 文档不出现真实endpoint密钥；
- Runtime API Key不写入测试快照；
- 资源清单记录资源ID、名称、地域和用途，但不记录密钥值；
- 上传压缩包前排除`.venv`、`.env`、真实`agentkit.yaml`、日志和缓存。

---

## 18. 请假 Agent 独立拆分门禁

以下全部通过前，禁止拆分 `hr-leave-agent`：

### 18.1 会话门禁

- AgentKit会话资源接入成功；
- Runtime重启后流程可继续；
- 多实例下状态一致；
- 同一session并发冲突有明确定义；
- 活动流程和槽位状态可结构化恢复。

### 18.2 身份门禁

- 员工身份来自可信来源；
- Runtime API Key与员工身份明确区分；
- employeeId不能由普通用户伪造；
- client secret不通过A2A传播；
- 远端Leave Agent可以在服务端获取所需凭据。

### 18.3 契约门禁

- 请假槽位Schema冻结；
- 待确认状态冻结；
- 用户确认语义冻结；
- 请假单Artifact冻结；
- 业务后端提取请假单JSON的方式已E2E验证；
- 自然语言回复不能替代结构化请假单；
- 失败、取消、改期和重新确认语义已定义。

### 18.4 副作用门禁

- 明确智能体只生成JSON还是直接提交；
- 当前结论仍为“后端提交”，不得在拆分时偷偷改成Agent直连提交；
- 请求幂等键已定义；
- 超时后的结果不确定性已处理；
- 不允许自动重复提交；
- 人工接管路径真实存在或明确标记为尚未实现。

### 18.5 质量门禁

- 现有5条请假对话评测全部通过；
- 新增多轮恢复测试通过；
- 远端失败不会丢失已收集槽位；
- 延迟处于用户可接受范围；
- 跨Runtime Trace完整。

通过后由用户明确发出“开始拆分请假Agent”，Codex才能执行第二阶段。

---

## 19. 切换与回滚

### 19.1 切换顺序

固定顺序：

1. 独立Agent本地验证；
2. 独立Agent开发Runtime验证；
3. A2A显式调用验证；
4. Orchestrator开发Runtime接入；
5. 端到端用例；
6. 失败注入；
7. 开启开发空间语义检索；
8. 语义路由对照；
9. 删除本地双轨；
10. 冻结第一阶段。

### 19.2 回滚条件

出现以下任一情况必须回滚到最近一个已验收批次：

- 现有21条评测出现未解释退化；
- 会话串用户；
- 密钥进入A2A消息、日志或Trace；
- 本人数据被路由到咨询Agent；
- 请假办理被错误送入语义发现；
- 远端故障导致编排循环；
- A2A返回无法校验的结构；
- JUMP标记失效；
- 原本只读路径产生写操作；
- 依赖升级使用了不受支持的组合。

### 19.3 回滚方式

- 回滚Runtime到上一已知正常版本；
- 暂时关闭A2A调用入口；
- 不删除失败现场日志和Trace；
- 不通过临时复制代码绕过问题；
- 修复后重新从失败批次执行验收；
- 回滚不等于永久保留双轨。

---

## 20. 本地 Codex 必须产出的文档

实施结束时至少交付：

1. `docs/current-baseline.md`；
2. `docs/target-architecture.md`；
3. `docs/sdk-upgrade-report.md`；
4. `docs/a2a-contracts.md`；
5. `docs/a2a-routing.md`；
6. `docs/session-and-identity.md`；
7. `docs/deployment-runbook.md`；
8. `docs/resource-inventory.md`；
9. `docs/test-report.md`；
10. `docs/migration-report.md`；
11. `apps/leave_agent/SPLIT-GATE.md`。

文档必须写真实执行结果。未执行的云端验证必须标记“未验证”，不得用方案描述冒充完成事实。

---

## 21. 每批提交要求

建议提交边界固定为：

1. `chore: freeze hr agent baseline and migration evidence`
2. `chore: upgrade agentkit and veadk dependencies`
3. `refactor: establish multi-app hr agent workspace`
4. `feat: extract hr consult agent application`
5. `feat: extract employee data agent application`
6. `feat: add explicit a2a orchestration`
7. `test: add a2a contracts and failure scenarios`
8. `docs: add deployment and resource runbooks`
9. `refactor: remove completed local migration paths`
10. `docs: freeze leave agent split gates`

不得把依赖升级、目录重构、Agent拆分和云端配置混在同一个提交。

---

## 22. 禁止本地 Codex 自行发挥的事项

本地 Codex 明确禁止：

- 一次性拆出请假Agent；
- 把每个工具包装成Agent；
- 把本人数据查询留在咨询Agent；
- 让Orchestrator继续直接查知识库；
- 通过复制代码避免共享领域包设计；
- 长期保留本地与A2A双轨；
- 新建带版本号目录；
- 私自更换模型；
- 私自开启thinking；
- 私自修改业务话术；
- 私自改变“后端提交请假单”的业务结论；
- 把`client_secret`放入A2A消息；
- 以Runtime API Key代替员工身份；
- 未经确认创建生产资源；
- 自动为冲突资源名添加随机后缀；
- 遇到依赖冲突时选择较低版本凑合；
- 继续使用SDK私有成员；
- 删除失败测试来获得全绿；
- 放宽断言掩盖路由错误；
- 用Mock成功冒充真实A2A成功；
- 在没有Trace证据时声称跨Runtime链路完整；
- 修改无关业务功能。

遇到上述未决事项或外部阻塞时，必须停止对应批次并输出：事实、证据、影响、可选项，等待用户决定。

---

## 23. 第一阶段最终验收标准

只有同时满足以下条件，才可宣布本轮拆分完成：

### 工程

- 单仓多应用结构完成；
- 共享领域包边界清楚；
- 应用间无Agent实例导入；
- 无版本式长期目录；
- 无循环依赖；
- 无真实密钥入库。

### Agent

- `hr-orchestrator`、`hr-consult-agent`、`hr-employee-data-agent`可分别启动；
- 咨询和员工数据Agent可分别部署；
- AgentCard职责清晰；
- 两个Agent已注册至开发A2A空间；
- 显式A2A调用成功；
- 语义检索按预期区分咨询和本人数据；
- 请假仍留在本地且行为不变。

### 状态与安全

- user/session/request标识跨Runtime可追踪；
- 密钥不进入A2A消息和Trace；
- 员工身份不依赖用户自行声明；
- 会话资源验证结果明确；
- 多实例风险没有被隐瞒。

### 质量

- 原21条评测全部通过；
- 新增契约测试通过；
- 新增A2A E2E通过；
- 失败注入通过；
- JUMP行为不变；
- 数字查询不编造；
- 制度咨询有来源；
- 拆分前后延迟与成本有真实对比。

### 清理

- 已完成路径的临时双轨已删除；
- 旧的咨询和本人数据装配已从Orchestrator移除；
- 无未说明的废弃文件；
- 部署、销毁、回滚和资源清单齐全；
- 请假拆分门禁文档完成，但未擅自执行。

---

## 24. 交给本地 Codex 的执行指令

将本文件作为冻结实施规范。执行时必须：

1. 先审计当前真实代码并输出与第3章的差异；
2. 严格按第14章批次顺序执行；
3. 每批开始前列出将修改的文件和不会修改的范围；
4. 每批结束后执行对应测试并更新证据文档；
5. 一个批次失败时不得跳到后续批次；
6. 云端写操作前必须停下来让用户确认资源与计费；
7. 不得把第18章请假Agent拆分作为本轮完成条件；
8. 不得写出另一份改变本方案核心边界的新方案；
9. 如发现本方案与官方SDK真实能力冲突，只报告冲突和证据，不自行改目标；
10. 最终按第23章逐条给出“通过/未通过/未验证”和证据位置。

本方案没有授权本地 Codex自行扩展到 Skill、MCP、长期记忆、安全围栏或 Harness 的代码接入。这些属于A2A拆分完成后的独立体验专题，避免在同一轮同时引入过多变量；但当前目录和Agent边界必须为后续接入保留清晰位置。

---

## 25. 后续 AgentKit 体验衔接

第一阶段拆分完成后，后续按以下独立专题推进：

1. AgentKit Session资源与多实例恢复；
2. AgentKit Memory及记忆提取策略；
3. Skill智能工坊：创建、调试、评估、注册；
4. Skills中心：版本、空间与多Agent复用；
5. AIO/Browser/Skills Sandbox；
6. 盖亚只读接口接入MCP Gateway；
7. Identity入站登录、员工身份与出站凭据；
8. 安全围栏与攻击日志；
9. AgentKit评测集、评估器与实验；
10. Trace数据回流；
11. 会话满意度、情绪诊断与人工评估；
12. Harness邀测能力；
13. 通过全部门禁后拆分`hr-leave-agent`。

这些专题不得反向破坏本方案冻结的Agent职责边界。
