# HR Agent 单仓多应用工程

当前仓库已形成三个独立应用。生产Orchestrator固定通过A2A调用Consult与Employee Data，不再保留本地生产回退；Leave Agent仍在Orchestrator进程内。

```text
hr-orchestrator（127.0.0.1:8000）
├── 本地 leave_agent
├── 本地 page_jump、取消引导和人工入口
├── A2A → hr-consult-agent（127.0.0.1:8101）
└── A2A → hr-employee-data-agent（127.0.0.1:8102）
```

## 应用职责

| 路径 | 职责 |
|---|---|
| `apps/orchestrator` | 固定意图路由、本地页面/JUMP/人工入口、Leave装配、A2A消费者 |
| `apps/orchestrator/local_leave` | 本地请假槽位收集、校验和请假单JSON生成 |
| `apps/consult_agent` | 制度、福利、系统操作和文档问答；独立A2A服务 |
| `apps/employee_data_agent` | 当前员工本人余额、医疗期、工龄和年假折算；独立只读A2A服务 |
| `apps/leave_agent` | Leave未来拆分门禁；本轮没有可启动实现 |
| `packages/agent_runtime/a2a` | 通用请求上下文、官方SDK服务/客户端适配、Artifact辅助和敏感字段检测 |
| `packages/hr_domain` | 与Agent框架无关的领域常量、Schema、规则、Gaia客户端和响应适配 |

共享A2A包不包含AgentCard、业务契约、路由、Knowledge、Gaia、身份映射、提示词或Agent实例。

## 本地联调

Orchestrator通过`HR_CONSULT_A2A_URL`和`HR_EMPLOYEE_DATA_A2A_URL`指定两个A2A端点；本地默认为8101/8102。远端失败显式返回安全错误，不会静默回退。

启动命令：

```bash
# 终端1：Consult A2A
uv run python -m apps.consult_agent

# 终端2：Employee Data A2A
uv run python -m apps.employee_data_agent

# 终端3：Orchestrator
uv run python agent.py
```

独立服务的健康检查和AgentCard：

| 服务 | 健康检查 | AgentCard |
|---|---|---|
| Consult | `http://127.0.0.1:8101/health` | `http://127.0.0.1:8101/.well-known/agent-card.json` |
| Employee Data | `http://127.0.0.1:8102/health` | `http://127.0.0.1:8102/.well-known/agent-card.json` |
| Orchestrator | `http://127.0.0.1:8000/health` | 不作为本批A2A提供者 |

## 验证

```bash
uv sync --locked
uv run pytest -q
uv run pytest -q tests/eval/test_eval.py -m eval
uv run pytest -q tests/eval/test_consult_eval.py -m consult_eval
uv run pytest -q tests/eval/test_employee_data_eval.py -m employee_data_eval
```

真实A2A和Viking测试还需相应`RUN_REAL_*`开关及本机真实模型/Viking配置。完整命令、身份配置、安全边界和最新结果见：

- [`deployment/README.md`](deployment/README.md)
- [`docs/local-multi-agent-a2a-report.md`](docs/local-multi-agent-a2a-report.md)
- [`.env.example`](.env.example)

## 云端开发验证状态

三个开发Runtime、`hr-agents-dev`及两个公网Runtime来源A2A Agent已创建并保留，准确ID、版本、镜像、费用风险和当前阻塞见：

- [`docs/cloud-deployment-report.md`](docs/cloud-deployment-report.md)
- [`deployment/resource-inventory.yaml`](deployment/resource-inventory.yaml)

云端兼容语义回归（legacy semantic regression）21/21 通过；生产拓扑业务验收（Public A2A → Semantic Router → Local Leave / 远程 Consult / 远程 Employee Data）另见 `tests/e2e/production_topology/` suite。Consult 和 Employee Data 最终使用 `e827b01-stage1-six-fixes`，Orchestrator 使用 `e827b01-stage1-orchestrator-a2a-only`。

> 说明：21/21 仅证明单进程兼容 Agent 能处理旧基线，不能证明生产拓扑业务迁移正确。只有 production-topology suite 全绿且真实模型/Viking/Gaia 验收通过后，才能写成"生产拓扑业务验收通过"。

分享源码时只能运行`python -m scripts.source_archive <output.zip>`从Git已跟踪文件生成归档；Runtime镜像禁止使用全目录复制。详细门禁见[`deployment/README.md`](deployment/README.md)。
