# 新批次5阶段0：云端只读预检

## 2026-08-11 阶段1最终事实修正

本节保留下文阶段0和阶段1早期判断过程，同时记录最终事实：三个开发Runtime均为公网端点，两个A2A Agent使用`NetworkType=public`和Runtime `key_auth`；未创建VPC、子网、NAT或PrivateLink。Consult与Employee Data Runtime最终为版本5/Ready/镜像`e827b01-stage1-six-fixes`，Orchestrator为版本4/Ready/镜像`e827b01-stage1-orchestrator-a2a-only`。

云端健康、会话、SSE、JUMP、Consult真实Viking和Employee Data `source=stub`均已验证。六条中间失败已在业务断言不变的前提下修复；云端双轨清理前和清理后均为21/21。Orchestrator生产装配中的local Consult与local Employee Data路径已删除，最终事实以`docs/cloud-deployment-report.md`首节和`deployment/resource-inventory.yaml`为准。

## 1. 结论

### 2026-08-10 A2A注册成功与Orchestrator创建阻塞

修正`CreateA2aAgent`Space字段后，Consult和Employee Data均以Runtime来源、`NetworkType=public`成功注册到`hr-agents-dev`，状态为`running`，默认版本为`1.0.0`。两个平台读回URL与Runtime AgentCard URL一致，无Key和错误Key均返回401，正确Key的直接A2A调用通过。

随后创建`hr-orchestrator-dev`时，`CreateRuntime`在创建资源前拒绝`ArtifactType=Image`：

```text
Field: ArtifactType
Code: InvalidParameter.ArtifactType
Message: The specified ArtifactType is invalid.
RequestId: 20260810142835547BCFCAF0E2541CE9F6
```

读回确认`hr-orchestrator-dev`数量为0，没有产生Runtime或API Key资源。本次命中“新的真实平台错误”停止条件，未改用其他`ArtifactType`再次创建。

### 2026-08-10 阶段1实际验证后修正

本节是对后续实际API结果的追加记录，不删除下文阶段0当时的判断过程。

- AgentKit私网Runtime需要在`CreateRuntime`时开启私网访问，并选择VPC和子网；不能在Runtime创建后仅靠A2A注册参数将公网endpoint变成私网endpoint。
- Runtime来源A2A Agent的`RuntimeConfig.NetworkType`必须与目标Runtime的endpoint类型一致。
- 本批已创建的Consult和Employee Data Runtime均是公网endpoint；`NetworkType=private`实际返回`network type private does not match runtime endpoint`。
- 项目负责人随后批准本次开发验证使用`NetworkType=public`，保持Runtime `key_auth`，不创建VPC、子网、NAT或PrivateLink。
- 公网注册不再返回endpoint类型错误，已进入AgentCard校验；但平台拒绝了中文Skill名称，错误为`InvalidParameter.agentCard.skills[0].name`。因此跨Runtime A2A仍未完成。
- 私网部署只作为未来生产化选项，不属于本批实施范围。

2026-08-10 续行结果：两张AgentCard已全部改为可打印ASCII元数据，Consult和Employee Data Runtime已使用新不可变镜像发布为版本3，规格、公网、`key_auth`、环境变量与Min/Max未变。从两个真实Runtime经官方`A2ACardResolver`读回的AgentCard已通过正式模型、全字符串ASCII、Skill唯一性、HTTPS URL、本地地址和Secret检查，直接Runtime A2A冒烟也通过。

已按授权删除原公网AgentCard校验失败记录`a-yesitqdywwt8ocx1om2u`。随后的单次Consult注册请求在创建资源前被接口参数校验拒绝：实际API要求`A2aSpaceId`，本次请求使用了指令示例中的`SpaceId`。错误码`InvalidParameter.`，RequestId`202608101404200231719DD0E125218A65`。目标Space读回仍为0个Agent，没有产生新failed记录。按“Consult只尝试一次”与“公网A2A注册失败即停止”的门禁，未改名参数重试。

阶段0只读盘点已完成到当前CLI和公开API能够确认的范围，但部署前置条件不满足，状态为**阻塞**。本阶段没有执行任何云端写操作，也没有创建Git提交。

阻塞事实：

1. `default`项目在`cn-beijing`下没有可用VPC和子网，无法直接采用“Orchestrator公网入口、两个被调Runtime私网、私网A2A”的默认网络方案。
2. Consult和Employee Data当前入口只监听`127.0.0.1:8101/8102`，AgentCard也固定发布本地地址；现有镜像只暴露8000并只启动`agent.py`。当前制品不能直接作为两个独立云Runtime使用。
3. AgentKit CLI 0.8.1没有SessionStore列表命令；按公开文档尝试的只读OpenAPI请求返回404，因此不能把SessionStore记为“不存在”，只能记为“未确认”。
4. 预检过程中一次只读查看被Git忽略的真实`agentkit.yaml`时，终端输出包含了`MODEL_AGENT_API_KEY`、火山AK/SK和Runtime API Key的值。值未写入Git、本文或资源清单，未执行轮换。该输出违反了阶段0的终端脱敏要求，必须在部署前单独决定凭据轮换和现有Runtime更新顺序。

因此，当前不能进入阶段1。后续即使收到“允许开始云端部署”，也应先明确批准部署适配、网络选择和凭据处置，重新通过本地门禁后才能执行首个云端写操作。

## 2. 起点与本地门禁

| 项目 | 结果 | 证据 |
|---|---|---|
| Git HEAD | `e827b0107cb4af956065e8aa2a3dd530a11987ec` | `git rev-parse HEAD` |
| 分支 | `main` | `git branch --show-current` |
| 初始工作区 | 仅`docs/hr-agent-a2a-split-plan.md`未跟踪 | `git status --short` |
| 冻结方案SHA-256 | `6ffe551afa44ced4996c94a9f2cac015f794d42411cc95d92f3a08520a87f252` | `shasum -a 256` |
| local/local 21条 | `21 passed`，6 warnings，135.61秒 | 真实模型与Viking配置，未修改业务代码 |
| 本地三服务A2A | `35 passed`，145 warnings，167.13秒 | 真实本地网络、真实模型/Viking、Employee Data Stub |
| 独立入口 | 三个入口均存在 | `agent.py`、`python -m apps.consult_agent`、`python -m apps.employee_data_agent` |
| 依赖 | AgentKit 0.8.1、veADK 1.1.0、google-adk 2.2.0、a2a-sdk 0.3.7 | `pyproject.toml`、`uv.lock` |

阶段0未修改提示词、模型、Knowledge、Agent职责或A2A业务响应格式。

## 3. 账号与范围

| 项目 | 只读事实 |
|---|---|
| 账号 | `2101533667` |
| 当前身份 | 火山主账号身份，TRN为`trn:iam::2101533667:root`；凭据来自本地环境链，未在本文记录值 |
| AgentKit CLI | 0.8.1；`agentkit whoami`显示未进行CLI SSO登录 |
| 实际项目 | 原HR Runtime位于`default`，不是从名称推测 |
| 地域 | `cn-beijing` |
| 只读权限 | Runtime、实例、A2A、AgentKit资源、Viking、IAM、CR、Quota、APM/TLS查询成功；SessionStore查询未成功 |
| 关联服务 | `apig`、`apmplus_server`、`ark`、`cr`、`id`、`mem0`、`privatelink`、`TLS`、`vikingdb`等为Enabled |

查询失败不等于资源不存在。SessionStore按“未确认”处理。

## 4. 当前线上资源

完整的本项目相关条目见[resource-inventory.yaml](../deployment/resource-inventory.yaml)。

### 4.1 原HR Agent Runtime

| 字段 | 当前值 |
|---|---|
| 名称 / ID | `hr-agent-nbgplh40` / `r-yerqme2fb4gumvo41qdj` |
| 项目 / 地域 | `default` / `cn-beijing` |
| 状态 | Ready，当前版本1 |
| 规格 | 2 vCPU、4096 MiB |
| 实例 | 1个Running/Ready |
| 弹性 | MinInstance=1、MaxInstance=10、MaxConcurrency=100 |
| 鉴权 / 网络 | `key_auth`，API Key名称`API-KEY-u17dymup`，公网入口`https://s6ifts5crqam93ibb6o7p.apigateway-cn-beijing.volceapi.com`；未记录Key值 |
| APM | 已启用；TLS日志查询可用 |
| 资源关联 | Runtime详情未关联AgentKit Knowledge、Memory、MCP Toolset或Tool |
| 环境变量键 | `CLOUD_PROVIDER`、`ENABLE_APMPLUS`、`GAIA_DRY_RUN`、`KB_BACKEND`、`MODEL_AGENT_API_KEY`、`MODEL_AGENT_CLIENT_REQ_ID`、`MODEL_AGENT_NAME`、`OTEL_RESOURCE_ATTRIBUTES`、`OTEL_SERVICE_NAME`、`REGION`、`RUNTIME_IAM_ROLE_TRN`、`VOLCENGINE_ACCESS_KEY`、`VOLCENGINE_SECRET_KEY`；未读取到本文 |
| 会话 | 代码仍使用`ShortTermMemory(backend="local")` |
| 近期流量 | 近7日仅发现8条服务日志，最后时间为2026-08-05；未读取正文，不能据此证明有或没有真实业务流量 |
| 本批处理 | 保留不动，不更新、不发布、不重启、不扩缩容、不切流量 |

### 4.2 A2A

| 类型 | 事实 |
|---|---|
| Space | 1个：`Default`，ID `as-yeq7yn15a8b1qjcc1anl`，语义发现关闭 |
| Agent | 1个失败状态的Runtime来源Agent，ID `a-yeqhqei874b1qjcc1igm`，名称为空、版本缺失、网络类型未返回，与本项目计划名称不冲突 |
| 计划名称冲突 | 六个固定名称均未发现同名Runtime、Space或Agent |

### 4.3 其他资源

| 资源 | 只读事实 |
|---|---|
| SessionStore | 未确认；CLI不支持列表，公开OpenAPI只读请求返回404 |
| AgentKit Knowledge | 1个Ready资源`agentkit_test`，未关联原Runtime |
| Viking | 四个现有collection均存在：`policy`、`handbook`、`salary`、`childcare`；继续复用，不创建、不删除 |
| Memory | 2个Ready资源，与本批无关联 |
| MCP | 2个Service，0个Toolset；与原HR Runtime无关联 |
| Skill | 5个running Skill；与本批无关联 |
| IAM | 原Runtime使用`AgentKit_Runtime_Default_ServiceRole_nnfyh40`；只记录角色名和用途 |
| 镜像 | 复用CR实例`agentkit-platform-2101533667`、命名空间`agentkit`；原HR仓库为私有，标签采用时间戳规则；保留策略未由只读SDK确认 |
| VPC / 子网 | `default`项目下均为0 |
| 配额 | Runtime 200、已用9；单Runtime实例上限20；A2A Space 25、已用1；单Space Agent上限100，计划资源数量不超配额 |

## 5. 本地资源测量

测量在macOS本地逐个独立启动服务，统计服务进程组RSS；客户端不计入。Consult使用真实Viking，Employee Data使用明确Stub。云端镜像调度和网络冷启动尚未测量。

| 服务 | 启动峰值 | 空闲稳定 | 单请求峰值 | 端口就绪 | 健康就绪 | 单请求耗时 |
|---|---:|---:|---:|---:|---:|---:|
| Orchestrator | 289.4 MiB | 289.5 MiB | 423.3 MiB | 1.779s | 1.797s | 3.690s |
| Consult | 283.1 MiB | 283.2 MiB | 418.3 MiB | 1.499s | 1.510s | 8.396s |
| Employee Data | 217.0 MiB | 217.1 MiB | 355.1 MiB | 1.148s | 1.159s | 3.393s |

按单请求峰值增加30%后分别为550.3、543.8、461.6 MiB。平台公开规格的最小内存为2 GiB、最小CPU为1 vCPU，因此三个Runtime均推荐1 vCPU / 2 GiB，而不是按本地值压到512 MiB。该规格同时满足30%余量和平台规格梯度。

## 6. 拟议Runtime规格

以下为解除部署入口和网络阻塞后的建议，不代表已创建。

| 配置 | hr-orchestrator-dev | hr-consult-agent-dev | hr-employee-data-agent-dev |
|---|---|---|---|
| CPU / 内存 | 1 vCPU / 2 GiB | 1 vCPU / 2 GiB | 1 vCPU / 2 GiB |
| Min / Max | 0 / 1 | 0 / 1 | 0 / 1 |
| MaxConcurrency | 10 | 10 | 10 |
| 发布 | 创建后仅发布一个开发版本 | 同左 | 同左 |
| 入站鉴权 | 公网`key_auth` | 私网A2A入站鉴权 | 私网A2A入站鉴权 |
| APM / 日志 | 验证期启用，测试后随资源处理 | 同左 | 同左 |
| SessionStore | 默认不关联；单独可选 | 不关联 | 不关联 |
| Knowledge | 不关联 | 不关联AgentKit Knowledge；复用四个Viking collection | 不关联 |
| 构建入口 | `python -m agent`，8000，`/health` | 当前需部署适配后监听`0.0.0.0:8000`，`/health` | 当前需部署适配后监听`0.0.0.0:8000`，`/health` |
| 冷启动 | 本地健康约1.8s；云端待测 | 本地约1.5s；云端待测 | 本地约1.2s；云端待测 |
| 主要额外调用 | Ark、Gaia Leave配置 | Ark、Viking | Ark、Gaia或Stub |

`MinInstance=0`由平台支持，但云端冷启动、A2A首次发现和实例保活时间必须在阶段1实测。若首次测试不稳定，只能在记录额外费用并获批后临时改为1，不能自行调整。

### 6.1 环境变量与Secret边界

仅记录键名，不记录值。三者共同使用`MODEL_AGENT_NAME`、`MODEL_AGENT_API_KEY`和非敏感日志/Trace配置。

- Orchestrator：`HR_CONSULT_TRANSPORT=a2a`、`HR_EMPLOYEE_DATA_TRANSPORT=a2a`、两个A2A端点、Leave所需Gaia配置、页面和会话配置。不得复制Consult的四个Viking collection。当前敏感数据进入`session.state`的问题仍未修复。
- Consult：`KB_BACKEND`、四个`KB_COLLECTION_*`、`VIKING_KNOWLEDGE_*`、火山AK/SK或STS键。不得配置Gaia、employeeId、请假工具或页面跳转。
- Employee Data：`EMPLOYEE_DATA_BACKEND`、`EMPLOYEE_IDENTITY_MAP_JSON`、`EMPLOYEE_REF_SECRET`；方案B才配置`GAIA_CORP_ID`、`GAIA_CLIENT_SECRET`、`GAIA_GRANT_TYPE`及Gaia endpoint。不得配置Knowledge。

当前代码的Viking公开SDK适配显式读取AK/SK环境变量，尚未验证仅凭Runtime IAM角色可用。Secret应从Runtime安全配置或经批准的Secret服务注入；AgentKit CLI 0.8.1的本地配置会把值写入被忽略的`agentkit.yaml`，不能把该文件作为阶段1长期Secret管理方案。

## 7. 拟议A2A资源

| 资源 | 建议 |
|---|---|
| `hr-agents-dev` | 新建开发Space，`cn-beijing/default`，语义发现关闭 |
| `hr-consult-agent` | 以`Runtime`来源关联`hr-consult-agent-dev`，私网，版本1.0.0 |
| `hr-employee-data-agent` | 以`Runtime`来源关联`hr-employee-data-agent-dev`，私网，版本1.0.0 |

使用Runtime来源可由平台绑定Runtime服务地址和网络，避免手工登记漂移的标准AgentCard URL；这不消除应用自身AgentCard必须可访问且不得发布`127.0.0.1`的前置问题。本批保持显式调用，不开启语义发现，不注册Leave Agent。

## 8. 网络、鉴权与身份

推荐目标仍为：业务调用方经公网`key_auth`访问Orchestrator；Orchestrator经私网A2A访问两个被调Runtime。Consult和Employee Data无需面向公网。

当前阻塞是项目内没有VPC/子网。进入阶段1前必须从以下两个方向中批准一个：

1. 推荐：新增开发VPC和子网，再创建三个私网可达Runtime；VPC名建议`hr-agents-dev-vpc`，子网名建议`hr-agents-dev-subnet`，CIDR和可用区必须先在控制台验证无冲突后冻结。VPC/子网属于新增写操作，不能包含在“仅六个AgentKit资源”的默许范围内。
2. 备选：三个Runtime先使用公网网络并各自启用`key_auth`，只用于短时跨Runtime验证；公网流量与暴露面更大，不符合默认私网目标，不能作为无差异替代。

Runtime API Key只证明调用应用有权访问Runtime，不能证明`user_id`对应哪个员工。Employee Data仍必须走`A2A user_id → TrustedIdentityResolver → 内部employeeId`；当前`EMPLOYEE_IDENTITY_MAP_JSON`只是两个测试身份映射，不是企业SSO或AgentKit Identity。

API Key和服务端Secret只能保存在获批的Runtime安全配置/Secret服务中，不进入A2A消息、Git、日志、Trace或Artifact。建议每个Runtime使用独立Key，不能复用原线上Runtime Key。

## 9. Gaia、Session与Identity选择

| 项目 | 阶段0结论 |
|---|---|
| Gaia方案A | Employee Data Runtime显式使用Stub，只验证跨Runtime A2A；响应必须`source=stub`，不得写成真实Gaia通过 |
| Gaia方案B | 通过安全配置注入真实Gaia凭据，并验证真实员工数据；当前尚无真实验证证据 |
| Orchestrator SessionStore | 跨RuntimeA2A本身不强制；默认不新建，作为单独可选项 |
| 不关联的限制 | `ShortTermMemory(local)`在Runtime重启后丢失，多实例不一致；即使MaxInstance=1也不能宣称重启恢复或持久会话可靠 |
| Leave拆分 | SessionStore和Identity未完成前不拆分，保持本地 |

## 10. Trace、日志与Knowledge分析

阶段1应验证：

```text
Orchestrator请求
→ 固定路由
→ A2A目标
→ 远端Runtime
→ 模型调用
→ Knowledge或Employee Data工具
→ Artifact
→ Orchestrator最终响应
```

受控观测字段：`request_id`、`session_id`、脱敏`user_id`、调用方/目标Agent、Agent版本、A2A状态、模型调用、Token、延迟、工具名、Knowledge scope、`source/score`、错误码。不得记录完整知识切片、原始employeeId、完整`session.state`或任何凭据。

现有账号已开通APMPlus和TLS，原Runtime能查询Trace日志。为跨Runtime验证，建议开发验证期间三个Runtime都启用APMPlus和日志；APMPlus不是运行A2A的必需组件，但它是验证跨Runtime Trace的推荐证据源。

待验证项：

- 本地自定义`knowledge.search` span是否会被AgentKit/APM自动展示；
- Viking官方SDK直调是否能关联AgentKit“Knowledge分析”；预计普通Trace可见，但平台Knowledge专属分析不能先行宣称支持；
- A2A空间是否自动透传同一trace上下文；
- MinInstance=0冷启动时日志和Trace是否完整。

## 11. 费用与持续计费风险

价格只采用当前公开文档计费单位，不使用猜测的控制台折扣。

| 项目 | 可确认事实 | 金额未知项 / 风险 |
|---|---|---|
| Runtime实例 | CPU 0.000097375元/vCPU/秒；内存0.000015456元/GB/秒。1 vCPU/2 GiB为0.461833元/小时、11.083997元/实例/天；3个实例连续运行一天为33.251990元 | 账号折扣、实际保活秒数未知 |
| MinInstance=0 | 无保底实例；实例运行时仍按秒计费 | 首次冷启动和自动缩零保活时间未知 |
| 镜像构建和存储 | CR可能按实例、存储和流量计费 | 当前Micro实例具体单价、构建流水线费用、保留策略需控制台确认 |
| API Gateway公网调用 | Runtime公网流量公开价0.8元/GB | 是否叠加网关请求费、账号套餐未知 |
| 私网A2A | A2A文档说明私网连通本身免费 | Runtime计算、模型和工具调用仍计费 |
| 公网流量 | 0.8元/GB | 实际流量未知 |
| APMPlus | 服务端Trace每月25GB免费，超出0.4元/GB；指标每月1亿点免费，超出0.18元/百万点 | 当前账号当月已用量未知 |
| TLS日志 | 按量日结，可按功能或写入流量计费 | 当前项目计费模式、写入/存储/查询单价需费用中心确认 |
| 模型调用 | 当前`doubao-seed-1.6`公开价按上下文/输出长度分档；常规在线≤32k时输入0.8元/百万Token，短输出2元/百万Token、其他输出8元/百万Token | 实际分档、缓存、账号合同价未知 |
| Viking | 公开价按资源、存储、向量化、rerank和LLM调用分别计费 | 四个现有collection的版本/规格未由列表API返回，增量金额未知 |
| Gaia | 外部企业接口 | 官方内部计费规则未知 |
| SessionStore | 后端RDS/Serverless PostgreSQL等单独计费 | 本批默认不创建；若选择需单独报价 |
| A2A Space/Agent | AgentKit公开计费页未列出独立计费单元 | 不能据此宣称免费，需费用中心确认 |

建议阶段1验证窗口为2小时。最坏一天新增资源数量为3个Runtime实例（Max=1）、1个Space、2个Agent，以及用户若选择的VPC/子网和观测数据；原Runtime继续保持1个实例，不计作本批新增但仍持续计费。测试结束立即按用户选择保留、缩容到0或销毁。Runtime、Space、Agent和新镜像删除后不能按原ID恢复；四个原Knowledge collection和原Runtime不得删除。

官方依据：

- [AgentKit计费项与价格](https://www.volcengine.com/docs/86681/2480915)
- [AgentKit按量计费说明](https://www.volcengine.com/docs/86681/2480916)
- [Runtime创建规格](https://www.volcengine.com/docs/86681/1844831)
- [A2A概述与私网通信](https://www.volcengine.com/docs/86681/2229299)
- [A2A Space](https://www.volcengine.com/docs/86681/2229303)
- [注册A2A Agent](https://www.volcengine.com/docs/86681/2229304)
- [APMPlus计费](https://www.volcengine.com/docs/6431/69089)
- [TLS计费概述](https://www.volcengine.com/docs/6470/1215813)
- [方舟模型价格](https://www.volcengine.com/docs/82379/1544106)
- [Viking Knowledge价格](https://www.volcengine.com/docs/84313/1414457)
- [容器镜像服务计费概述](https://www.volcengine.com/docs/6420/79158)

## 12. 拟议阶段1写操作清单

当前清单**不具备执行条件**，仅供审批：

1. 经用户选择后创建`hr-agents-dev-vpc`和`hr-agents-dev-subnet`，或明确批准公网备选；两者不能默认替换。
2. 为三类服务准备可部署入口和非本地AgentCard地址，构建三个可区分入口的开发镜像/制品；重新执行全部本地门禁。
3. 创建`hr-agents-dev`，语义发现关闭。
4. 创建并发布`hr-consult-agent-dev`。
5. 创建并发布`hr-employee-data-agent-dev`，按用户选择使用Stub或真实Gaia。
6. 注册`hr-consult-agent`和`hr-employee-data-agent`，来源均为Runtime。
7. 创建并发布`hr-orchestrator-dev`，配置两个transport为A2A。
8. 为三个Runtime创建独立开发API Key并注入经批准的服务端Secret；不复用原线上Runtime Key。
9. 按用户选择启用三个开发Runtime的APMPlus/TLS；默认不创建SessionStore。
10. 测试结束后按用户选择保留、缩容到0或删除本次新建资源。
11. 本次终端凭据暴露的轮换、原Runtime配置更新和旧凭据撤销必须作为单独明确批准的安全写操作，不能由“允许部署”自动推定。

不得执行`agentkit launch`去覆盖原`agentkit.yaml`所指向的线上Runtime。三个新Runtime必须使用独立的去密部署配置和明确目标ID。

## 13. 固定部署、验证和回滚顺序

### 部署与验证

执行以下固定顺序前，必须先解除本报告的部署入口、网络和凭据处置阻塞；该前置处理不构成云端部署步骤。

1. 再次确认本地全部门禁。
2. 创建或确认开发A2A空间。
3. 部署Consult Runtime。
4. 验证Consult健康、AgentCard和直接A2A。
5. 部署Employee Data Runtime。
6. 验证Employee Data健康、AgentCard和直接A2A。
7. 注册两个A2A Agent。
8. 验证空间内显式调用。
9. 部署新的Orchestrator Runtime。
10. 配置两个transport为A2A。
11. 执行跨Runtime 21条核心评测。
12. 执行故障、鉴权和Trace验证。
13. 验证原线上Runtime未受影响。
14. 成功后删除新Orchestrator中的local Consult和local Employee Data生产路径。
15. 保留Leave本地路径。
16. 完成最终报告。
17. 按用户选择保留、缩容到0或销毁开发资源。

### 回滚与销毁

1. 停止新Orchestrator流量。
2. 保留原线上Runtime。
3. 注销本批新注册的两个A2A Agent。
4. 删除或缩容本批新Runtime。
5. 删除开发A2A Space。
6. 不触碰四个原Knowledge collection。
7. 不删除原线上Runtime。
8. 不删除未明确属于本次创建的资源。

若阶段1明确批准并创建了新VPC/子网或新镜像，只能在新Runtime删除后、且用户选择销毁时单独删除；不得借此改变上述原资源保护顺序。

## 14. 对现有线上的影响

推荐方案仍是保留原`hr-agent-nbgplh40`不动，新建3个开发Runtime和1个开发Space。只要不复用原Runtime配置、不轮换其正在使用的凭据、不修改其API Key和流量入口，部署验证对原线上服务应为隔离。当前是否仍有真实业务流量未验证，因此不能把原Runtime视为可覆盖资源。

终端凭据暴露使“凭据完全不动”和“立即轮换”形成冲突：立即撤销可能影响原Runtime；不轮换则延长已暴露凭据风险。必须由项目负责人单独批准一个可回滚的轮换顺序，阶段0不代替选择。

## 15. 阶段0待决定事项

1. 原Runtime是否继续保持完全不动：推荐是。
2. Gaia选择A（Stub，只验证A2A）或B（真实凭据与真实数据）：不代替选择。
3. 是否在解除部署入口和网络阻塞后创建3个新Runtime：推荐是。
4. 私网方案是否批准新增VPC/子网；否则是否接受短时公网备选。
5. 是否启用APMPlus/TLS：推荐在2小时验证窗口启用。
6. 是否关联SessionStore：推荐本次不新建、不关联，并明确不验证重启/多实例会话一致性。
7. 测试结束后保留、缩容到0或销毁：推荐先缩容到0保留短时复核，再按费用决策销毁。
8. 已输出到任务终端记录的凭据如何轮换：必须单独批准，不能在阶段0执行。

## 16. 阶段0边界

- 云端写操作：**未执行**。
- Git提交：**未提交，等待阶段1**。
- 冻结方案：未修改、未提交。
- 真实Gaia：未验证。
- SessionStore：未确认。
- 当前状态：阻塞，等待项目负责人处理上述前置条件；不得自行进入阶段1。
