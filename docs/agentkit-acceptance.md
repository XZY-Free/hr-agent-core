# AgentKit 远端验收

## 范围与当前入口

当前唯一可执行的验收入口是 `tests/agentkit` 下的 **AgentKit 远端 HTTP 客户端**用例：

```bash
uv sync --locked
uv run pytest -q            # 默认 testpaths=["tests/agentkit"]，即 uv run pytest -q tests/agentkit
```

- `pyproject.toml`：`testpaths=["tests/agentkit"]`、`addopts="--tb=short --no-showlocals"`。
- `tests/conftest.py` 在收集前对 `config.args` 做白名单校验，只放行 `tests/agentkit` 及其中已存在的文件/目录/`::node`；禁止 `--pyargs` 与 `--showlocals`，纯 `--collect-only` 在该目录内允许。不自动读取本地配置文件（`.env`/`agentkit.yaml` 等）、不加载模型环境、不启动本地服务。
- `uv run pytest -q` 不会在本地装配业务 Agent。自动读取/收集的是 `tests/agentkit` 下对已部署云 Runtime 的远端客户端用例。云端凭据由执行测试的进程环境安全注入，不要求用户输入密码；服务端配置另归属 AgentKit。

## 最近一次通过结果（2026-09-05，调用已发布 AgentKit 开发服务）

| 项 | 值 |
|---|---|
| 命令 | `uv run pytest -q`（默认 `tests/agentkit`） |
| total | 258 |
| passed | 258 |
| failed | 0 |
| skipped | 0 |
| 耗时 | 925.86 秒（15:25） |

- 全量 `tests/agentkit` 远端用例对已发布三个 dev Runtime 全部通过，覆盖 WP01-WP07（身份、请假状态与确定性规则、员工数据多余额、考勤量化计算、语义路由与 continuation、附件安全边界、生产拓扑与公共 Cancel 不支持契约）。
- 脱敏结果保存于 `../tests/e2e/logs/agentkit-remediation-final-v33-v14-v11-2026-09-05.xml`（不进入版本管理）。`HR_ACCEPTANCE_EXPECTED_IMAGES_JSON` 为操作方从已发布配置读取的待验收不可变镜像映射，内存注入、非业务凭证。

**整体结论（限定范围）**：`业务迁移非假实现整改：PASS（AgentKit 开发环境；Gaia 为授权 stub 边界）`。真实 Gaia/OAuth 未验证，不计为已通过；Gaia 为授权 stub 边界，不作为 FAIL 依据，也不被当作「真实 Gaia 已通过」。

> 历史（非当前）：早前 21/27 为 preflight 未通过的 RED 快照；22 pass / 3 fail 为身份门禁初版历史 RED；早前 v7/v9 快照为旧镜像。均为历史记录，不代表当前已通过状态。

## 测试客户端配置（安全注入）

云端凭据由**执行测试的进程环境**安全注入（非业务 Runtime 自动注入客户端），服务端配置另归属 AgentKit。只写占位，不写真实值，不要求粘贴密码。

| 变量 | 用途 | 必需 |
|---|---|---|
| `VOLCENGINE_ACCESS_KEY` | 云 SDK 访问 Key | 是（安全注入） |
| `VOLCENGINE_SECRET_KEY` | 云 SDK 访问 Secret | 是（安全注入） |
| `VOLCENGINE_REGION` | 云 SDK 区域 | 可选；当前默认 `cn-beijing` |
| `VOLCENGINE_SESSION_TOKEN` | STS 临时凭据 | STS 时 |
| `HR_ACCEPTANCE_ORCHESTRATOR_API_KEY` | Orchestrator Runtime 服务端 API Key | 是 |
| `HR_ACCEPTANCE_CONSULT_API_KEY` | Consult Runtime 服务端 API Key | 是 |
| `HR_ACCEPTANCE_EMPLOYEE_API_KEY` | Employee Data Runtime 服务端 API Key | 是 |
| `HR_ACCEPTANCE_EXPECTED_IMAGES_JSON` | 待验收不可变镜像映射（JSON 对象，键精确为 `orchestrator` / `consult` / `employee_data`） | 是（必填，不得回填制造成功） |

模型 / Gaia 桩数据 / 身份 / Knowledge 都在 AgentKit 服务端，测试不能注入 session state 伪造业务事实。

## 已发布云端快照（2026-09-05，已验证）

| 服务 | 部署版本 | 不可变镜像 | 关键后端 | 备注 |
|---|---|---|---|---|
| Orchestrator | v33 | `agentkit-platform-2101533667-cn-beijing.cr.volces.com/agentkit/hr-agent-vkba:ec927bc-wp07-final-confidence-7e97ace657c5` | `GAIA_BACKEND=stub` | 公共 `hr-assistant` 入口 + 身份/Gaia 服务端装配 |
| Employee Data | v11 | `agentkit-platform-2101533667-cn-beijing.cr.volces.com/agentkit/hr-agent-vkba:ec927bc-wp03-employee-balances-cdf7856146a1` | `EMPLOYEE_DATA_BACKEND=stub` | 有服务端可信身份 map/ref |
| Consult | v14 | `agentkit-platform-2101533667-cn-beijing.cr.volces.com/agentkit/hr-agent-vkba:ec927bc-wp07-final-attendance-aff56a4e32c8` | `KB_BACKEND=agentkit` | 4 个 collection 已配置 |

三个 dev Runtime 均 Ready、health 200。当前已发布镜像 suffix：Orchestrator `ec927bc-wp07-final-confidence-7e97ace657c5`、Consult `ec927bc-wp07-final-attendance-aff56a4e32c8`、Employee Data `ec927bc-wp03-employee-balances-cdf7856146a1`；路径前缀统一为 `agentkit-platform-2101533667-cn-beijing.cr.volces.com/agentkit/hr-agent-vkba`。

> 历史（非当前）：早前快照为 `e827b01-stage1-orchestrator-a2a-only`（AgentCard `root_agent/0.0.1`）、`e827b01-stage1-six-fixes` 以及 WP01 identity 镜像（suffix `ec927bc-wp01-identity-19103f428827`），均为旧镜像；现行版本见上表。A2A Space / 注册 Agent 仅登记在 [`deployment/resource-inventory.yaml`](../deployment/resource-inventory.yaml)，当前状态待复核。

## 云端已发布并验证（原「本地已修正、云未发布」）

以下已在当前已发布三个 Runtime 镜像上生效并经远端客户端验证，非仅本地源码修正：

- `deployment/runtime_entry.py` 已映射 `orchestrator → apps.orchestrator.public_a2a`（不再走 `agent.py`）；
- `packages/hr_domain/gaia/config.py` 在显式 `GAIA_BACKEND=stub` 且 `GAIA_DRY_RUN=true` 时返回不带凭据的配置；默认 `gaia` 仍校验四项，未知 backend 拒绝；
- 身份 / 员工数据侧 `identity_unverified` 失败不再被 LLM 文本覆盖为 `completed/error_code null`（TurnOutput 识别结构化 `identity_unverified` 终态）；
- A2A 续接先校验首条消息原主体与 context 再改写 history，跨主体抢占被拒绝且原属主可恢复；
- 公共 A2A Cancel 不支持：注册 / AgentCard 契约 `cancel=false`；cancel 请求以官方 `UnsupportedOperationError`（JSON-RPC `-32004`）拒绝，不描述为已交付的取消生命周期。

## 授权边界：Gaia stub

Gaia 保留 `GAIA_BACKEND=stub`（用户明确授权的边界，非阻塞项），服务端配置 `GAIA_DRY_RUN=true`、`EMPLOYEE_DATA_BACKEND=stub`。真实 Gaia 接入与 OAuth 缓存证据**未验证**，不计为已通过，不索取 Gaia 凭据。服务端可信身份（`EMPLOYEE_IDENTITY_MAP_JSON` / `EMPLOYEE_REF_SECRET`）仍必需，且不是 Gaia 例外。

`GAIA_STUB_JSON` / `EMPLOYEE_DATA_STUB_JSON` 为 JSON 字符串配置（非文件路径），留空必填，不造内容；stub 成功响应必须 `source=stub`。

## WP01-WP07 状态（授权边界内 PASS，整体结项）

已通过（授权云端服务 + Gaia stub 边界）：

- Orchestrator 云 Runtime 已配置并验证 `EMPLOYEE_IDENTITY_MAP_JSON` / `EMPLOYEE_REF_SECRET`（服务端可信身份，非 Gaia 例外）；
- AgentCard 名称/URL 合规，测试已按 `HR_ACCEPTANCE_EXPECTED_IMAGES_JSON` 核对三个 Runtime 的镜像（当前已发布版本见上表）；
- 新整改代码（含 `runtime_entry`、Gaia 配置修正、身份/A2A 续接修正）已部署到云，公共入口为更新后的 `hr-assistant`；
- WP01-WP07 在授权边界内 PASS：身份门禁（WP01）、Leave 状态与确定性规则（WP02）、员工数据多余额（WP03）、考勤量化计算（WP04）、语义路由与 continuation（WP05）、附件安全边界与解析（WP06）、生产拓扑与公共 Cancel 不支持契约（WP07）；整体结论 **业务迁移非假实现整改：PASS（AgentKit 开发环境；Gaia 为授权 stub 边界）**。

例外 / 明确未包含（不得写成已通过）：

- 真实 Gaia 接入与 OAuth 缓存证据**未验证**（Gaia 为授权 stub 边界）；
- 请假最终下游提交仍为工程包明确排除的 dry-run / fake 边界，未发生真实 HR 写；
- 附件解析不依赖外部 SnowHarness resolver：缺失 resolver / reference 一律 fail closed，不宣称存在外部 resolver 集成；
- 公共 A2A Cancel 不支持（`cancel=false`），不将移除的取消生命周期作为交付功能。

## 测试语义与完成判定

- 远端 preflight（`tests/agentkit/test_wp01_environment.py`）、身份门禁（`tests/agentkit/test_wp01_identity.py`）与各 WP 业务用例共同构成当前 `tests/agentkit`，全量 258 项已对已发布三个云 Runtime 通过。
- 不虚构通过的业务 curl/响应；`health 200`/AgentCard 旧入口只作为历史实际发现记录，不当作当前已通过证据。
- 旧 `cloud_core_eval` / `cloud_a2a_smoke` 走 legacy/stub 且不完整，不作为当前验收入口（本任务不删除它们）。
- 结论中不把 Gaia 授权 stub 边界当作「真实 Gaia 已通过」；授权边界内的 PASS 以真实远端证据收口，例外项（真实 Gaia/OAuth、Leave 下游 dry-run、附件外部 resolver、A2A cancel）明确列出、不虚化为已通过。
