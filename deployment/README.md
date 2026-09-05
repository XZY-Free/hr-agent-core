# 开发环境部署与 AgentKit 远端验收

本手册不再提供「电脑本地三服务启动」步骤与 localhost curl 演示。当前验收入口是 `tests/agentkit` 下对已部署 AgentKit Runtime 的远端 HTTP 客户端用例。

## 源码归档与 Runtime 镜像边界

对外分享源码时只能从 Git 已跟踪文件生成归档：

```bash
python -m scripts.source_archive dist/hr-agent-source.zip
```

归档清单允许 Git 已跟踪的 `.env.example`，但不得包含真实 `.env`、其他 `.env.*`、`agentkit*.yaml`、`.runtime-secrets.json`、`.stage1-cloud-state.json`、`artifacts/`、`tests/**/logs/`、缓存目录或已有 ZIP。清单门禁失败时不得生成或分享归档，也不得通过读取文件内容排查。

Runtime 镜像只复制 `requirements.txt`、`agent.py`、`apps/`、`packages/` 和 `deployment/`。禁止恢复 `COPY . .`；`scripts/`、`tests/`、`docs/` 以及所有本地配置和证据文件不得进入镜像。推送前必须运行镜像文件边界与已知 Secret 扫描，扫描只输出命中数量。原线上 `hr-agent` 未执行写操作。

## 当前部署快照（已发布并验证）

截至 2026-09-05，三个 dev Runtime 均 Ready、health 200，均已发布并通过完整 AgentKit 远端验收（WP01-WP07 授权边界内 PASS）：

| 服务 | 部署版本 | 关键后端 | 备注 |
|---|---|---|---|
| Orchestrator | v33 | `GAIA_BACKEND=stub` | 公共 `hr-assistant` 入口 + 身份/Gaia 服务端装配 |
| Employee Data | v11 | `EMPLOYEE_DATA_BACKEND=stub` | 有服务端可信身份 map/ref |
| Consult | v14 | `KB_BACKEND=agentkit` | 4 个 collection 已配置 |

当前已发布不可变镜像：Orchestrator `agentkit-platform-2101533667-cn-beijing.cr.volces.com/agentkit/hr-agent-vkba:ec927bc-wp07-final-confidence-7e97ace657c5`（v33）、Employee Data `agentkit-platform-2101533667-cn-beijing.cr.volces.com/agentkit/hr-agent-vkba:ec927bc-wp03-employee-balances-cdf7856146a1`（v11）、Consult `agentkit-platform-2101533667-cn-beijing.cr.volces.com/agentkit/hr-agent-vkba:ec927bc-wp07-final-attendance-aff56a4e32c8`（v14）。本轮初版修复 public 入口/共享 identity map+ref/GaiaProvider 持有 client，后版修正 Leave `identity_unverified` 丢失与 A2A 续接先改 history 再校验 owner（Owner guard 在 SDK 历史改写前检查首条消息原主体与 context，错误保留为 `rejected/identity_unverified`）。保护资源规格/配置与环境不变。

> 历史（非当前）：早前快照 `e827b01-stage1-orchestrator-a2a-only`（AgentCard `root_agent/0.0.1`）与 `e827b01-stage1-six-fixes` 为旧镜像，现已替换。A2A Space / 注册 Agent 仅登记在 [deployment/resource-inventory.yaml](resource-inventory.yaml)，**登记状态，待复核**，不能当作实时已部署验证。

**云端已生效（经 Codex 远端 `tests/agentkit` 用例验证，合计 258 passed / 0 failed / 0 skipped，耗时 925.86 秒）**：

- Orchestrator 已配置 `EMPLOYEE_IDENTITY_MAP_JSON` / `EMPLOYEE_REF_SECRET`（公共 `TrustedIdentityResolver.from_env` 需要，服务端可信身份）；
- AgentCard 名称/URL 合规，测试已按 `HR_ACCEPTANCE_EXPECTED_IMAGES_JSON` 核对三个 Runtime 的镜像（当前已发布版本见上表）；公共 `hr-assistant` 入口已更新；
- `deployment/runtime_entry.py` 已映射 `orchestrator → apps.orchestrator.public_a2a`（不再走 `agent.py`）；
- `packages/hr_domain/gaia/config.py` 已在显式 `GAIA_BACKEND=stub` 且 `GAIA_DRY_RUN=true` 时返回不带凭据的配置（仅 stub 可用；默认 `gaia` 仍校验四项，未知 backend 拒绝）。

Gaia 为**用户明确授权的 stub 边界**（`GAIA_BACKEND=stub`、`EMPLOYEE_DATA_BACKEND=stub`、`GAIA_DRY_RUN=true`），已在授权 stub 边界内验证通过；真实 Gaia 接入与 OAuth 缓存未验证、不计为已通过。服务端可信身份（`EMPLOYEE_IDENTITY_MAP_JSON` / `EMPLOYEE_REF_SECRET`）已配置且必需，不是 Gaia 例外。

## 服务端配置（AgentKit 远端验收，均为安全注入）

各变量只留空占位/模板值，不写示例真实值；凭据通过 Runtime secret/IAM 注入，不进 Git、日志或 Trace。

| 变量 | 作用 |
|---|---|
| `HR_ASSISTANT_A2A_HOST` / `HR_ASSISTANT_A2A_PORT` | 公共入口监听：`0.0.0.0` / `8000` |
| `HR_ASSISTANT_A2A_PUBLIC_URL` | 公网可通告 URL：留空必填，不得写 loopback |
| `HR_ASSISTANT_A2A_AUTH_MODE` / `HR_ASSISTANT_A2A_BEARER_TOKEN` | `bearer` + Runtime Access Credential |
| `HR_CONSULT_A2A_URL` / `HR_EMPLOYEE_DATA_A2A_URL` | 下游 A2A 端点：留空必填，不写 loopback |
| `HR_CONSULT_RUNTIME_API_KEY` / `HR_EMPLOYEE_DATA_RUNTIME_API_KEY` | 下游 Runtime 服务端 API Key |
| `HR_A2A_TIMEOUT_SECONDS` | 下游 A2A 超时（默认 `30`） |
| `HR_CONSULT_A2A_BASE_URL` / `HR_EMPLOYEE_DATA_A2A_BASE_URL` | 下游 AgentCard 基础 URL |
| `MODEL_AGENT_NAME` / `MODEL_AGENT_API_KEY` | 模型（AgentKit 服务端） |
| `KB_BACKEND` | `agentkit`（Consult 已配置） |
| `KB_COLLECTION_*` | 四个 collection 映射：留空必填 |
| `VIKING_KNOWLEDGE_*` | 按资源配置；可选项为空时使用官方 SDK 默认，代码不硬编码 |
| `VOLCENGINE_ACCESS_KEY` / `VOLCENGINE_SECRET_KEY` / `VOLCENGINE_REGION` / `VOLCENGINE_SESSION_TOKEN` | 火山引擎 AK/SK/REGION/STS |
| `GAIA_BACKEND` | `stub`（授权假数据；干跑时不要求真实 Gaia 凭据） |
| `EMPLOYEE_DATA_BACKEND` | `stub`（授权假数据） |
| `GAIA_DRY_RUN` | `true`（授权假数据方式） |
| `GAIA_CORP_ID` / `GAIA_CLIENT_SECRET` / `GAIA_GRANT_TYPE` / `GAIA_SCHEDULE_TENANT` | 真实 Gaia 服务端配置；仅 `GAIA_BACKEND=gaia` 下必需，`stub` 干跑不要求（云端已生效） |
| `GAIA_STUB_JSON` / `EMPLOYEE_DATA_STUB_JSON` | 授权 stub 配置：JSON 字符串（非文件路径），留空必填，不造内容 |
| `EMPLOYEE_IDENTITY_MAP_JSON` | 服务端可信映射：留空必填 |
| `EMPLOYEE_REF_SECRET` | 共享身份密钥（生成不可逆 `employee_ref`） |

## 测试客户端与当前验收入口

```bash
uv sync --locked
uv run pytest -q
```

- `testpaths=["tests/agentkit"]`，`addopts="--tb=short --no-showlocals"`；默认只收集 `tests/agentkit` 客户端用例，不装配本地业务 Agent、不自动读取本地配置文件、不启动本地服务。
- 测试客户端配置（安全注入，只留空占位）：`VOLCENGINE_ACCESS_KEY` / `VOLCENGINE_SECRET_KEY` / `VOLCENGINE_REGION` / `VOLCENGINE_SESSION_TOKEN`，`HR_ACCEPTANCE_ORCHESTRATOR_API_KEY` / `HR_ACCEPTANCE_CONSULT_API_KEY` / `HR_ACCEPTANCE_EMPLOYEE_API_KEY`，以及 `HR_ACCEPTANCE_EXPECTED_IMAGES_JSON`（待验收不可变镜像映射，不得从当前云镜像回填制造成功）。这些是**执行测试进程**环境安全注入；服务端配置另归属 AgentKit。
- 模型 / Gaia 桩数据 / 身份 / Knowledge 都在 AgentKit 服务端，测试不能注入 session state 伪造业务事实。
- 远端 preflight 与身份门禁由 `tests/agentkit/test_wp01_environment.py` + `tests/agentkit/test_wp01_identity.py` 提供；全量 `tests/agentkit` 远端用例合计 **258 项已通过**（命令：`uv run pytest -q`，即 `uv run pytest -q tests/agentkit`，凭据由操作方在执行进程环境安全注入），JUnit 证据见 [`docs/agentkit-acceptance.md`](../docs/agentkit-acceptance.md)。不虚构通过的业务 curl/响应；真实 Gaia/OAuth 未验证为授权 stub 边界例外。

完整门禁、真实快照、范围与阻塞见 [`docs/agentkit-acceptance.md`](../docs/agentkit-acceptance.md)。

## 历史脚本（不作为当前验收入口，本任务不删除）

- 旧 `cloud_core_eval` / `cloud_a2a_smoke` 走 legacy/stub 且不完整，不再列为当前验收入口；
- 历史 21/21 兼容语义回归与本地 A2A 报告仅作为历史记录保留，不代表生产拓扑业务验收通过。

## 云端写操作边界

**验收目标**是三个 dev Runtime（`hr-orchestrator-dev` / `hr-consult-agent-dev` / `hr-employee-data-agent-dev`）；原线上正式 `hr-agent` 未修改，不属于本次验收对象。文档不因此声称「允许发布」——发布仍需既有授权。

执行任何云端写操作前必须满足并在对应批次/审批中提交：三个 Runtime 地域与规格、A2A Space 与两个 A2A Agent 注册信息、复用资源/API Key/IAM/服务端 Secret 清单、Employee Data 真实身份提供方与 Gaia 凭据注入方式、部署顺序/回滚/销毁与现有线上 `hr-agent` 影响、完整测试报告、项目负责人明确回复「允许开始云端部署」。

未获批准时禁止 `agentkit launch`、Runtime/A2A 资源写操作、持续计费资源创建和云端删除。文档声明不构成部署授权；不得因文档提及权限而擅自部署，也不得凭本地代码声称云上已更正。
