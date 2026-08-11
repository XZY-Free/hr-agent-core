# AgentKit 云端多 Runtime 部署报告

## 结论

### 2026-08-11 多Runtime与A2A工程收口完成

六条云端失败已逐层定位并修复，没有修改21条用例的业务断言：

| 用例 | 根因 | 修复层 |
| --- | --- | --- |
| `quick_tomorrow` | 云端Orchestrator没有显式Gaia Stub，排班查询进入无效Gaia鉴权 | 开发Runtime的Gaia Stub配置与请求时动态日期 |
| `gender_mismatch` | 请假资格查询被Gaia鉴权阻断 | 开发Runtime的Gaia Stub配置 |
| `rest_day` | 排班和提交工具被Gaia鉴权阻断 | 开发Runtime的Gaia Stub配置与请求时日期计算 |
| `balance_query` | Employee Data Artifact未丢数字，但云端Stub映射返回8天而非冻结测试身份的4天 | Employee Data Stub配置 |
| `personal_data_not_kb` | Employee Data Artifact未丢数字，但云端Stub医疗期为4天而非21天 | Employee Data Stub配置 |
| `doc_qa` | 文档内容只存在于Orchestrator会话上下文，Consult Runtime只能重新下载不可用的测试URL | 严格白名单的跨Runtime文档引用与脱敏内容封装 |

最终验证：

| 门禁 | 结果 |
| --- | --- |
| 本地原21条基线 | 21/21 |
| 本地三服务A2A | 35/35 |
| 云端双轨清理前 | 21/21，`cloud-core-eval-20260811-121009.jsonl` |
| 云端双轨清理后 | 21/21，`cloud-core-eval-20260811-123400.jsonl` |
| 镜像禁入路径 | 0 |
| 镜像最终文件已知Secret命中 | 0 |
| 镜像层已知Secret命中 | 0 |
| 归档门禁 | 5/5；允许跟踪的`.env.example`，拒绝真实`.env` |

产品装配中的local Consult与local Employee Data路径、两个transport切换模式和静默回退均已删除。Consult与Employee Data生产请求固定走A2A；Leave、JUMP、取消引导和人工入口仍在Orchestrator本地执行。本地三服务E2E、测试Fake和A2A业务格式测试保留，不构成生产回退。

最终保留资源：

| 资源 | ID | 版本/状态 | 镜像/类型 |
| --- | --- | --- | --- |
| `hr-consult-agent-dev` | `r-yesipag934nlc0d1rigw` | 5 / Ready | `e827b01-stage1-six-fixes` |
| `hr-employee-data-agent-dev` | `r-yesipooydceuszqwte9y` | 5 / Ready | `e827b01-stage1-six-fixes`，`source=stub` |
| `hr-orchestrator-dev` | `r-yesl0dq03knlc0d1qd1z` | 4 / Ready | `e827b01-stage1-orchestrator-a2a-only` |
| `hr-consult-agent` | `a-yesixjxerktkc0sp5232` | running | Runtime来源，public |
| `hr-employee-data-agent` | `a-yesixlrfggt8ocx1or9n` | running | Runtime来源，public |

原线上Runtime `r-yerqme2fb4gumvo41qdj`未收到任何创建、更新、发布、重启、扩缩容或鉴权修改请求；已有脱敏只读结果确认其ID、版本、镜像、规格、Min/Max/Concurrency、状态、环境变量键集和资源关联与冻结基线一致。

#### 终端鉴权字段事件

- 暴露对象：原线上Runtime鉴权字段`ApiKey`。
- 暴露位置：当前本地Codex任务终端记录。
- 原因：脱敏脚本未覆盖字段名`ApiKey`。
- 未进入范围：Git、提交、证据文档、业务日志、Trace、Artifact。
- 已采取措施：发现后立即停止，未复述具体值，不再查询完整鉴权配置。
- 负责人决定：接受终端记录的残余风险，本批不轮换。
- 后续要求：Runtime配置读取必须在请求层使用字段白名单，只允许输出资源ID、版本、镜像、规格、状态和环境变量键名；不允许先取得完整响应再做输出端脱敏。
- 凭据轮换：独立安全待办，不属于拆分与A2A工程。本文不记录字段值、片段、长度或哈希。

后续AgentKit Trace正式体验的脱敏定位证据：Consult request_id `42ff9e8e-73e7-453d-998c-d39179084aad`，Employee Data request_id `5d565255-7a44-465f-b6ef-31bc719f7d42`，时间窗口2026-08-11 12:34—12:37（Asia/Shanghai）。本批未扩展Trace实现，未进入Skill、MCP、Identity、Memory或SessionStore改造，未push。

### 2026-08-11 10:43 干净制品已部署，云端核心评测阻塞（历史执行记录）

本次先封堵了制品泄露面：Runtime Dockerfile已改为只复制`requirements.txt`、`agent.py`、`apps/`、`packages/`和`deployment/`，不再使用全目录复制；`.dockerignore`明确排除本地配置、Secret状态、脚本、测试、文档、缓存、日志和ZIP。新镜像`e827b01-stage1-clean`的最终文件系统和镜像层扫描结果均为0个已知Secret命中、0个禁入路径命中，摘要为`sha256:bffd2ef5e0d7a8aa2c272430f30c35f3e8bec25a1ffa76d34d8a848dd83ab6cc`。

三个开发Runtime已按Consult、Employee Data、Orchestrator顺序发布到该镜像并回到Ready：

| Runtime | ID | 版本 | 规格 | 健康 |
| --- | --- | --- | --- | --- |
| `hr-consult-agent-dev` | `r-yesipag934nlc0d1rigw` | 4 | 1000m/2048MiB，Min=0，Max=1，Concurrency=10 | 200 |
| `hr-employee-data-agent-dev` | `r-yesipooydceuszqwte9y` | 4 | 1000m/2048MiB，Min=0，Max=1，Concurrency=10 | 200 |
| `hr-orchestrator-dev` | `r-yesl0dq03knlc0d1qd1z` | 2 | 1000m/2048MiB，Min=0，Max=1，Concurrency=10 | 200 |

各Runtime的公网端点、`key_auth`、环境变量键和值、APMPlus/TLS、关联资源和规格保持不变。Orchestrator版本1与版本2的环境变量键和值相同，仅平台返回顺序变化。Consult正确Key调用完成真实Viking检索并返回5条带`source/score`的来源；Employee Data正确Key调用成功并明确`source=stub`。Orchestrator健康、会话创建、SSE及本地`[[JUMP:punch-details]]`均通过。

确认12个Runtime均不再引用旧标签后，已精确删除CR标签`e827b01-orchestrator-a2a-auth`和`e827b01-stage1-card-ascii`；`e827b01-stage1`及其他归属不明标签未删除。CR底层Blob是否立即物理清理由平台保留策略决定，因此在负责人决定不轮换凭据的前提下仍有残余风险。

随后通过`hr-orchestrator-dev`公网入口执行冻结的21条核心评测，结果为**15通过、6失败**。失败证据仅记录用例ID、HTTP状态、路由、request_id、工具名和断言类别，不记录回答正文或Secret：

| 用例 | 路由/状态 | 失败事实 |
| --- | --- | --- |
| `quick_tomorrow` | 本地Leave，`get_schedule`、`submit_leave`均调用 | 最终结论缺少冻结要求的提交关键词 |
| `gender_mismatch` | 本地Leave | 未调用`submit_leave`，缺少陪产假资格拒绝结论 |
| `rest_day` | 本地Leave，调用`get_schedule` | 对话未出现休息日/无需请假结论 |
| `balance_query` | Employee Data A2A，`succeeded` | 回答未命中冻结的4天表达断言 |
| `personal_data_not_kb` | Employee Data A2A，`succeeded` | 回答未命中冻结的21天表达断言 |
| `doc_qa` | Consult A2A，远端状态`failed` | 未形成`parse_document`成功结果，文档关键事实缺失 |

Consult制度类、育儿假、薪酬、试用期等跨Runtime用例成功；Employee Data年假折算成功；Leave仍保持本地，JUMP、取消引导和人工入口通过。`followup_present`本次核心断言和非阻塞追问指标均命中。由于6条核心业务断言失败，命中停止条件：未执行A2A专项扩展、Trace/APM/TLS后续观察、双轨生产路径删除、Orchestrator二次发布、清理后21条及最终提交。

证据文件：`tests/e2e/logs/cloud-core-eval-20260811-104358.jsonl`（Git忽略，仅含脱敏字段）。

### 泄露与制品边界

| 项目 | 当前事实 |
| --- | --- |
| 终端泄露 | 阶段0及后续一次误读未跟踪脚本时曾输出真实凭据；负责人决定本批不轮换，相关未跟踪脚本已删除，当前工作区已知Secret值扫描为0命中 |
| ZIP泄露 | 当前仓库未发现ZIP/TAR等本地归档；历史归档是否曾包含Secret无法从现有证据证明 |
| 镜像潜在泄露 | 两个旧标签已删除，但底层Blob物理清理取决于CR保留策略；`e827b01-stage1`按指令保留，未证明其历史层无Secret |
| 是否轮换 | 否，沿用负责人已接受风险的决定 |
| 干净镜像 | `e827b01-stage1-clean`，禁入路径0、最终文件Secret命中0、镜像层Secret命中0 |
| 三个Runtime最终镜像 | 均为`e827b01-stage1-clean` |
| 删除的旧标签 | `e827b01-orchestrator-a2a-auth`、`e827b01-stage1-card-ascii` |
| 归档门禁 | 已新增“仅Git跟踪文件”归档工具和禁入路径规则；当前清单检查因已跟踪`.env.example`命中`.env*`规则而失败，尚未生成或分享归档 |
| 残余风险 | 终端历史、CR未立即回收的Blob及保留的`e827b01-stage1`可能继续保留历史暴露面；未轮换凭据意味着风险持续存在 |

### 2026-08-10 两个A2A Agent已running，Orchestrator创建阻塞

Consult与Employee Data已使用冻结请求体成功注册：

| Agent | ID | 状态 | 版本 | Source | NetworkType |
| --- | --- | --- | --- | --- | --- |
| `hr-consult-agent` | `a-yesixjxerktkc0sp5232` | running | 1.0.0 | Runtime | public |
| `hr-employee-data-agent` | `a-yesixlrfggt8ocx1or9n` | running | 1.0.0 | Runtime | public |

两个平台Agent的Host、AgentCard名称、版本和Skill名称与对应Runtime一致。无Key和错误Key读AgentCard均返回401；使用对应Runtime现有Key的Consult真实Viking调用与Employee Data `source=stub`调用均成功。

已推送不可变Orchestrator镜像`e827b01-orchestrator-a2a-auth`，摘要`sha256:b8ebd70a1bf153646a0ff0382e5008af962d5e3b3fa63bacbcb78f0ab7e14115`。镜像中A2A Runtime API Key只通过`Authorization: Bearer`Header发送，不进入A2A消息、Artifact或日志。

创建`hr-orchestrator-dev`时，平台在资源创建前返回新错误：

```text
Field: ArtifactType
Code: InvalidParameter.ArtifactType
Message: The specified ArtifactType is invalid.
RequestId: 20260810142835547BCFCAF0E2541CE9F6
```

读回确认`hr-orchestrator-dev`数量为0，未创建Runtime或Orchestrator API Key。按“新的真实平台错误”停止，没有猜测其他`ArtifactType`并重试。云端21条、Trace、双轨清理和最终回归尚未执行。

### 2026-08-10 AgentCard ASCII修正后续行

两张AgentCard的全部JSON字符串叶子已按冻结值改为U+0020—U+007E，不含中文、换行、Tab、本地地址或API Key。本地和两个真实Runtime读回均完成`AgentCard` 模型、递归ASCII、Skill ID唯一性、security引用一致性、绝对HTTPS URL和Secret检查。Consult直接Runtime A2A返回真实Viking来源与score；Employee Data使用已配置的测试身份后返回`source=stub`。

新镜像为`e827b01-stage1-card-ascii`，摘要`sha256:05a20b2ecb68f1dbf1527cde9d028889016779e8b556e1ddfa175915dd056fc6`。Consult和Employee Data Runtime均已发布为版本3并回到Ready；CPU、内存、Min/Max、Concurrency、公网类型、`key_auth`、APM/TLS、环境变量键和关联资源摘要前后一致。

原公网AgentCard校验失败记录`a-yesitqdywwt8ocx1om2u`已精确删除。随后只执行了一次Consult注册请求，请求在资源创建前因Space字段名不匹配被拒绝：

```text
Code: InvalidParameter.
Message: binding: expr_path=A2aSpaceId, cause=missing required parameter
RequestId: 202608101404200231719DD0E125218A65
```

目标Space随后读回Agent数量为0，未留下新failed记录。由于指令限定Consult只尝试一次，且公网A2A注册失败是停止条件，本次没有将`SpaceId`改为平台实际要求的`A2aSpaceId`再次请求。Employee Data未注册，Orchestrator未创建。

新批次5阶段1于 2026-08-10 两次按停止条件暂停，仍未完成跨 Runtime A2A 部署。

`hr-consult-agent-dev` 和 `hr-employee-data-agent-dev` 已独立部署并通过直接 Runtime 验证；`hr-agents-dev` 已创建且语义发现关闭。但在以 Runtime 来源、`NetworkType=private` 注册 Consult A2A Agent 时，平台返回：

```text
Code: InternalError
Message: network type private does not match runtime endpoint
RequestId: 20260810122256093B0BC8E43BBAC801C9
```

项目负责人后续批准改用公网Runtime来源A2A。私网失败记录`a-yesiq3eigwt8ocx1pjf7`已按授权删除；但`NetworkType=public`注册进入AgentCard校验后，平台拒绝首个中文Skill名称：

```text
Code: InvalidParameter.agentCard.skills[0].name
Message: value contains a non-printable ASCII character at position 0
RequestId: 2026081013185334273F7DD976FB2D1210
```

本次请求留下新的无名称、`failed`记录`a-yesitqdywwt8ocx1om2u`。根据“公网A2A注册失败立即停止”的要求，未修改AgentCard，未继续注册Employee Data，未部署Orchestrator，未删除双轨路径。

## 起点

| 项目 | 结果 |
| --- | --- |
| Git HEAD | `e827b0107cb4af956065e8aa2a3dd530a11987ec` |
| 初始工作区 | 仅阶段0两个证据文件与未跟踪冻结方案 |
| 冻结方案 SHA-256 | `6ffe551afa44ced4996c94a9f2cac015f794d42411cc95d92f3a08520a87f252` |
| 项目 / 地域 | `default` / `cn-beijing` |
| 原 Runtime | `hr-agent-nbgplh40` / `r-yerqme2fb4gumvo41qdj` |

## 阶段0结论修正

- AgentKit私网Runtime需要在创建Runtime时开启私网访问并选择VPC/子网；A2A注册的`NetworkType`必须与目标Runtime endpoint类型一致。
- 本批已有两个开发Runtime是公网endpoint，所以`NetworkType=private`返回endpoint类型不匹配。
- 负责人已批准本次开发验证改用`NetworkType=public`，保持Runtime `key_auth`，不创建VPC、子网、NAT或PrivateLink。
- 公网请求已通过endpoint类型校验，但在中文Skill名称字段被平台拒绝，因此仍未成功注册。
- 私网部署仅保留为未来生产化选项，不再属于本批实施范围。

## 本地部署适配

### 启动入口

| 应用 | 云端入口 | 端口 | 健康检查 |
| --- | --- | --- | --- |
| Orchestrator | `deployment.runtime_entry` 的 `orchestrator` 分支 | `0.0.0.0:8000` | `/health` |
| Consult | `apps.consult_agent.cloud` | `0.0.0.0:8000` | `/health` |
| Employee Data | `apps.employee_data_agent.cloud` | `0.0.0.0:8000` | `/health` |

Consult 与 Employee Data AgentCard URL 由环境变量生成，本地默认仍是 `127.0.0.1:8101/8102`，云端使用对应 Runtime 地址。

### 制品

| 项目 | 值 |
| --- | --- |
| 镜像 | `agentkit/hr-agent-vkba:e827b01-stage1` |
| 镜像摘要 | `sha256:00d155617b59308a478f09f84a44df608da3c92cf5b50e94e68cde2e6c15566b` |
| 架构 | `linux/amd64` |
| 仓库 | 复用现有 CR 实例和仓库 |
| 标签 | 包含起点 Git 短 SHA，未使用 `latest` |

## 本地门禁

| 门禁 | 实际结果 |
| --- | --- |
| 云端入口单元/结构测试 | 14条通过；精简重跑10条通过 |
| 非评测测试 | 246 passed, 71 skipped, 34 deselected |
| 真实 Viking | 5 passed |
| Consult 独立评测 | 10 passed |
| Employee Data 独立评测 | 3 passed |
| Consult 本地真实 A2A | 14 passed |
| Employee Data 本地真实 A2A | 17 passed |
| `local/local` 根入口 | 21 passed |
| 三服务联合 A2A，含 `a2a/a2a` 21条与固定路由 | 35 passed |
| 三个本地镜像入口 | `/health` 均200；Consult 4 Skills；Employee Data 3 Skills |
| 依赖锁 | `uv lock --check` 通过 |
| SDK 私有成员扫描 | 通过 |
| 敏感值扫描 | 0命中 |
| `git diff --check` | 在云端写操作前通过 |

模型推荐追问仍是非阻塞质量指标，未被改为核心门禁。

## 凭据策略

- 复用了现有模型 API Key、火山 AK/SK 和 Viking 访问配置。
- 未创建模型 Key、IAM 用户、IAM 角色、AK/SK 或 STS 体系，未轮换或撤销任何旧凭据。
- AgentKit `CreateRuntime` 的 `key_auth` 公开请求结构只接受 `ApiKeyName/ApiKeyLocation`，不提供绑定旧 Key ID 或传入旧 Key 值的字段。因此平台为两个新 Runtime 各创建了1个必需 Key 资源：`hr-consult-agent-dev-key`、`hr-employee-data-agent-dev-key`。
- Key 值只写入 Git 忽略的本地运行文件，权限0600；未写入报告、测试证据或 Git。
- 本阶段未向新 Runtime 注入 Gaia 凭据。
- 已接受风险：阶段0的只读命令曾将旧凭据输出到任务终端记录；项目负责人已知情并决定本批不轮换。

## 云端资源与验证

### A2A Space

| 字段 | 结果 |
| --- | --- |
| 名称 | `hr-agents-dev` |
| ID | `as-yesioj26f4tkc0sp4xnl` |
| 项目 / 地域 | `default` / `cn-beijing` |
| 语义发现 | 关闭 |
| 创建请求 ID | `202608101158526E013EE540CAC4D7B8D9` |
| 保留 | 是 |

### Consult Runtime

| 字段 | 结果 |
| --- | --- |
| 名称 / ID | `hr-consult-agent-dev` / `r-yesipag934nlc0d1rigw` |
| 状态 / 版本 | Ready / 2 |
| 规格 | 1000m CPU，2048MiB，Min=0，Max=1，Concurrency=10 |
| 入站鉴权 | `key_auth` |
| APMPlus / TLS | APMPlus开启；TLS使用平台托管日志链路 |
| 关联资源 | 无 AgentKit Knowledge、SessionStore、Memory、MCP |
| 健康 | `/health` 200 |
| AgentCard | `hr-consult-agent` / 1.0.0 / A2A 0.3.0 / JSONRPC / streaming / 4 Skills |
| 真实 Knowledge | “迟到扣款制度是什么”成功，policy scope，5条来源，`content/source/score` 结构通过 |
| 职责拒绝 | 本人数据 `personal_data_not_allowed`；请假办理 `leave_request_not_allowed` |
| A2A 注册 | 公网类型匹配，但AgentCard中文Skill名称校验失败，未得到running Agent |

### Employee Data Runtime

| 字段 | 结果 |
| --- | --- |
| 名称 / ID | `hr-employee-data-agent-dev` / `r-yesipooydceuszqwte9y` |
| 状态 / 版本 | Ready / 2 |
| 规格 | 1000m CPU，2048MiB，Min=0，Max=1，Concurrency=10 |
| 数据源 | `source=stub` |
| Gaia | 未配置、未验证 |
| 关联资源 | 无 Knowledge、SessionStore、Memory、MCP |
| 健康 | `/health` 200 |
| AgentCard | `hr-employee-data-agent` / 1.0.0 / A2A 0.3.0 / JSONRPC / streaming / 3 Skills |
| 本人数据 | 年假余额、年假折算、医疗期均成功且 `source=stub` |
| 身份隔离 | 两个虚构 user_id 的 `employee_ref` 和数据均不同 |
| 越权拒绝 | 跨员工、制度、请假办理、`employeeId`、`target_employee_id`、未映射身份均按约定拒绝 |
| 泄露检查 | Artifact 与实例日志不含内部 employeeId、映射、引用密钥或凭据 |
| A2A 注册 | 未执行，因 Consult 注册失败后停止 |

### 私网 A2A 失败记录

| 字段 | 结果 |
| --- | --- |
| Space | `hr-agents-dev` / `as-yesioj26f4tkc0sp4xnl` |
| Agent ID | `a-yesiq3eigwt8ocx1pjf7` |
| 平台显示名称 | 空 |
| 状态 | failed |
| Source | Runtime |
| 请求 NetworkType | private |
| 目标 Runtime | `r-yesipag934nlc0d1rigw` |
| 错误 | `InternalError: network type private does not match runtime endpoint` |
| 请求 ID | `20260810122256093B0BC8E43BBAC801C9` |

该记录已于获得精确授权后删除，删除请求ID为`2026081013183153DAF98E19B61734CA37`。

### 公网 A2A AgentCard校验失败记录

| 字段 | 结果 |
| --- | --- |
| Space | `hr-agents-dev` / `as-yesioj26f4tkc0sp4xnl` |
| Agent ID | `a-yesitqdywwt8ocx1om2u` |
| 平台显示名称 | 空 |
| 状态 | failed |
| Source | Runtime |
| 请求 NetworkType | public |
| 目标 Runtime | `r-yesipag934nlc0d1rigw` |
| AgentCard首个Skill | ID `hr-policy-consultation`，名称`\u4eba力制度咨询`，首字符`U+4EBA` |
| 错误 | `InvalidParameter.agentCard.skills[0].name: value contains a non-printable ASCII character at position 0` |
| 请求 ID | `2026081013185334273F7DD976FB2D1210` |

`Default` Space 中原有失败 Agent `a-yeqhqei874b1qjcc1igm` 仍保持原状，未处理。

## 观测实际结果

| 项目 | Consult | Employee Data |
| --- | --- | --- |
| TLS 服务日志命中 | 52条 | 92条 |
| TLS 日志中非空 trace_id 数 | 1 | 6 |
| 凭据值命中 | 0 | 0 |
| request_id 字段 | 未观测到 | 未观测到 |
| model/token 相关记录 | 观测到相关记录，未展开业务内容 | 观测到相关记录，未展开业务内容 |
| Knowledge/tool/source/score 字段 | 未观测到 | 未观测到 |
| APM trace-span topic | 按 Runtime ID 与 service name 均未命中 | 按 Runtime ID 与 service name 均未命中 |

因 Orchestrator 未部署且 A2A Agent 未 running，未验证跨 Runtime 是否保持同一 Trace ID，也未验证 request_id/session_id 跨端关联。Viking 官方 SDK 直调在平台“Knowledge 分析”中的关联能力仍是未验证，不得写为支持。

## 原 Runtime 保护复核

`hr-agent-nbgplh40` / `r-yerqme2fb4gumvo41qdj` 完成后只读结果与阶段0字段逐项一致：

- Ready，版本1，1个Ready实例；
- 镜像标签仍为 `20260730170259`；
- 2000m CPU，4096MiB，Min=1，Max=10，Concurrency=100；
- `key_auth`的 Key 资源名与 location 未变；
- 公网入口未变；
- 环境变量键集未变；
- 无 A2A、SessionStore、Knowledge、Memory、MCP 新关联；
- `/health` 返回200。

本批未对原 Runtime 发出任何创建、更新、发布、重启、扩缩容或鉴权修改请求。

## 实际云端写操作

1. 向现有 CR 仓库推送不可变镜像 `e827b01-stage1`。
2. 创建 A2A Space `hr-agents-dev`，语义发现关闭。
3. 尝试创建 Consult Runtime 时传入不完整的显式 `TlsConfiguration`，平台在参数校验前拒绝，未留下 Runtime；请求 ID `20260810120344A062D05B23761E0384F6`。
4. 按 AgentKit 0.8.1 官方 Runtime 部署请求结构创建 `hr-consult-agent-dev`，平台同时创建1个必需 Runtime API Key。
5. 更新并发布 Consult 版本2，仅将 AgentCard 基础地址切换为实际 Runtime 地址。
6. 创建 `hr-employee-data-agent-dev`，平台同时创建1个必需 Runtime API Key。
7. 更新并发布 Employee Data 版本2，仅将 AgentCard 基础地址切换为实际 Runtime 地址。
8. 尝试在 `hr-agents-dev` 中以 Runtime 来源、`NetworkType=private` 注册 Consult Agent；请求失败并留下无名称failed记录。
9. 删除本批第8项产生的failed记录`a-yesiq3eigwt8ocx1pjf7`，未触碰Default Space历史记录。
10. 尝试以Runtime来源、`NetworkType=public`注册Consult Agent；endpoint类型校验通过，但中文Skill名称校验失败，留下新的无名称failed记录。
11. 推送新不可变镜像`e827b01-stage1-card-ascii`。
12. 仅更新两个开发Runtime的镜像并发布版本3，其他配置摘要未变。
13. 精确删除第10项的failed记录`a-yesitqdywwt8ocx1om2u`。
14. 只尝试一次Consult注册；请求因字段`SpaceId`未满足实际API必需字段`A2aSpaceId`而在创建资源前失败，未产生Agent记录。

除精确删除已授权的`a-yesiq3eigwt8ocx1pjf7`外，未执行其他资源删除、缩容、凭据轮换或原Runtime修改。

## 保留资源与费用风险

| 资源 | 保留状态 | 持续费用风险 |
| --- | --- | --- |
| `hr-consult-agent-dev` | Min=0，Max=1，保留 | Runtime调用、模型、Viking、APMPlus/TLS、镜像流量/存储 |
| `hr-employee-data-agent-dev` | Min=0，Max=1，保留 | Runtime调用、模型、APMPlus/TLS、镜像流量/存储 |
| `hr-agents-dev` | 保留 | A2A Space本身未找到独立公开单价 |
| `a-yesiq3eigwt8ocx1pjf7` | 已删除 | 不再持续计费 |
| `a-yesitqdywwt8ocx1om2u` | 已删除 | 不再持续计费 |
| `e827b01-stage1` 镜像 | 保留 | CR 存储与流量 |
| `e827b01-stage1-card-ascii` 镜像 | 保留 | CR 存储与流量 |
| 两个 Runtime API Key | 保留 | 未找到 Key 资源本身的独立公开单价 |

金额仍未知，需要用户在费用中心核对。后续如获得新授权执行删除，应按“停止流量 → 处理本批failed Agent 记录 → 删除两个新 Runtime及其Key → 删除 `hr-agents-dev` → 按保留策略处理镜像”的顺序，且不能触碰原 Runtime、Default Space、原 Knowledge collection 或任何非本批资源。

## 未验证与未执行

- `hr-consult-agent` 和 `hr-employee-data-agent` 的 running 注册、空间内显式调用；
- `hr-orchestrator-dev` 的创建、鉴权、跨 Runtime A2A 配置；
- 云端21条核心评测、SSE、JUMP、A2A故障注入；
- 跨 Runtime Trace、request_id/session_id关联、冷启动完整数据；
- 删除local Consult/Employee Data生产路径与清理后回归；
- 真实 Gaia、持久 Session、多实例会话一致性、正式 Identity、Skill、MCP、长期 Memory；
- Leave Agent 拆分，本批仍禁止执行。

## 偏差和停止依据

- 未修改提示词、模型、thinking、temperature、Knowledge scope、`top_k=5`、21条核心业务断言或Leave/JUMP行为。
- 未执行本指令外的云端资源创建。
- AgentCard ASCII问题已修正并在真实Runtime验证通过；最新单次注册在创建前因`SpaceId`/`A2aSpaceId`请求字段不匹配失败，未达到running。
- 命中停止条件：公网A2A注册失败；A2A Agent状态为failed；无法证明调用已跨越独立Runtime。

## 当前收口状态

本批未完成，因此多Agent拆分与A2A工程阶段尚未能宣布正式结束，也未进入AgentKit其他平台能力体验。公网endpoint与`NetworkType=public`、AgentCard全ASCII以及两个Runtime直接A2A均已验证；当前停在Consult注册请求的Space字段名不匹配。私网部署仅作为未来生产化选项，不属于本批。
