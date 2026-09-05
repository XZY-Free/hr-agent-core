# HR Agent 单仓多应用工程

当前仓库已形成三个独立应用。生产 Orchestrator 固定通过 A2A 调用 Consult 与 Employee Data，不再保留本地生产回退；Leave Agent 仍在 Orchestrator **云进程**内。本手册不再给出「电脑本地三服务启动」步骤与 localhost curl 演示——当前验收入口是 AgentKit 远端 HTTP 客户端（见下）。

```text
hr-orchestrator（容器监听 0.0.0.0:8000）
├── 进程内 leave_agent、page_jump、取消引导与人工入口
├── A2A → hr-consult-agent（云服务）
└── A2A → hr-employee-data-agent（云服务）
```

> 注：`local_leave`、`page_jump`、`人工入口` 是 Orchestrator 进程内架构术语，不代表「电脑本地三服务」环境；它们随 Orchestrator 作为同一个云进程部署。

## 应用职责

| 路径 | 职责 |
|---|---|
| `apps/orchestrator` | 固定意图路由、页面/JUMP/人工入口、Leave 装配、A2A 消费者 |
| `apps/orchestrator/local_leave` | 请假槽位收集、校验和请假单 JSON 生成（同 Orchestrator 云进程） |
| `apps/consult_agent` | 制度、福利、系统操作和文档问答；独立 A2A 服务 |
| `apps/employee_data_agent` | 当前员工本人余额、医疗期、工龄和年假折算；独立只读 A2A 服务 |
| `apps/leave_agent` | Leave 未来拆分门禁；本轮没有可启动实现 |
| `packages/agent_runtime/a2a` | 通用请求上下文、官方 SDK 服务/客户端适配、Artifact 辅助和敏感字段检测 |
| `packages/hr_domain` | 与 Agent 框架无关的领域常量、Schema、规则、Gaia 客户端和响应适配 |

共享 A2A 包不包含 AgentCard、业务契约、路由、Knowledge、Gaia、身份映射、提示词或 Agent 实例。

## 测试与验收（当前入口）

只有 `tests/agentkit` 下的 AgentKit 远端 HTTP 客户端用例是当前验收入口。

```bash
uv sync --locked
uv run pytest -q
```

（默认命令即 `uv run pytest -q`，等价于 `uv run pytest -q tests/agentkit`；凭据由操作方在执行进程环境安全注入，不要求用户输入密码。）

说明与边界：

- `uv run pytest -q` 现在**仅收集 `tests/agentkit`** 客户端用例（`pyproject` 默认 `testpaths=["tests/agentkit"]`），不会在本地装配业务 Agent，也不自动读取本地配置文件（`.env` 等）、不启动本地服务或模型。测试进程的云端凭据由执行进程环境安全注入，服务端配置另归属 AgentKit。
- 当前**已通过 AgentKit 开发云端完整业务验收**：全量 `tests/agentkit` 远端客户端用例 **258 passed / 0 failed / 0 skipped**（耗时 925.86 秒），JUnit 证据 [`tests/e2e/logs/agentkit-remediation-final-v33-v14-v11-2026-09-05.xml`](tests/e2e/logs/agentkit-remediation-final-v33-v14-v11-2026-09-05.xml)；WP01-WP07 在授权边界内 PASS，结论 **业务迁移非假实现整改：PASS（AgentKit 开发环境；Gaia 为授权 stub 边界）**。详见 [`docs/agentkit-acceptance.md`](docs/agentkit-acceptance.md)。
- 测试客户端配置下列安全注入项（只留空占位，不写示例真实值、不要求粘贴密码）：`VOLCENGINE_ACCESS_KEY` / `VOLCENGINE_SECRET_KEY` / `VOLCENGINE_REGION` / `VOLCENGINE_SESSION_TOKEN`，`HR_ACCEPTANCE_ORCHESTRATOR_API_KEY` / `HR_ACCEPTANCE_CONSULT_API_KEY` / `HR_ACCEPTANCE_EMPLOYEE_API_KEY`，以及 `HR_ACCEPTANCE_EXPECTED_IMAGES_JSON`（**待验收不可变镜像映射**：JSON 对象，键精确为 `orchestrator` / `consult` / `employee_data`，各绑定其待验收不可变镜像；不得从运行中云镜像回填制造成功）。身份数据（`HR_ACCEPTANCE_IDENTITY_ORACLE_JSON`）是操作方从已发布 stub 配置读取的测试主体/不可逆 ref/预期数据，内存注入，非业务凭证。
- 模型 / Gaia 桩数据 / 身份 / Knowledge 都位于 AgentKit 服务端，测试不能注入 session state 伪造业务事实。
- Gaia 保留 `GAIA_BACKEND=stub`、`EMPLOYEE_DATA_BACKEND=stub`、`GAIA_DRY_RUN=true`（用户明确授权边界），已在授权 stub 边界内验证通过；真实 Gaia 接入与 OAuth 缓存未验证、不计为已通过、不再索取 Gaia 凭据。服务端可信身份（`EMPLOYEE_IDENTITY_MAP_JSON` / `EMPLOYEE_REF_SECRET`）为真实必需配置，且不是 Gaia 例外（详见 [`docs/agentkit-acceptance.md`](docs/agentkit-acceptance.md)）。
- 不虚构通过的业务 curl/响应；历史快照（dev Runtime health 200、Orchestrator AgentCard `root_agent/0.0.1` 旧入口、以及 21/27 等 preflight 未通过）仅作为历史记录保留，不代表当前状态。当前已发布三个 Runtime 不可变镜像（`orchestrator` v33 / `consult` v14 / `employee_data` v11）并已通过完整验收门禁（见 [`docs/agentkit-acceptance.md`](docs/agentkit-acceptance.md)）。
- 历史 `cloud_core_eval` / `cloud_a2a_smoke` 走 legacy/stub 且不完整，不再列为当前验收入口（本工程包不删除它们）。
- 完整的当前可执行远端门禁、真实云端快照、范围与阻塞见 [`docs/agentkit-acceptance.md`](docs/agentkit-acceptance.md)。

## 云端开发验证状态（历史报告，非当前入口）

三个开发 Runtime、`hr-agents-dev` 及两个公网 Runtime 来源 A2A Agent 已创建并保留；历史兼容语义回归 21/21 与生产拓扑部署往返等，仅作为历史报告保留，**不代表当前状态**（当前业务验收以 `tests/agentkit` 远端结果为准：258/258，见上）。准确资源口径见：

- [`docs/cloud-deployment-report.md`](docs/cloud-deployment-report.md)（历史）
- [`docs/local-multi-agent-a2a-report.md`](docs/local-multi-agent-a2a-report.md)（历史）
- [`deployment/resource-inventory.yaml`](deployment/resource-inventory.yaml)（资源登记状态，待复核，不作实时已部署验证）
- [`deployment/README.md`](deployment/README.md)

分享源码时只能运行 `python -m scripts.source_archive <output.zip>` 从 Git 已跟踪文件生成归档；Runtime 镜像禁止使用全目录复制。详细门禁见 [`deployment/README.md`](deployment/README.md)。
