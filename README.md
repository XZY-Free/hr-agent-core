# HR Agent 单仓多应用工程

本仓库采用单仓多应用结构，让Orchestrator、制度咨询、员工本人数据和本地请假能力拥有明确代码归属，并为后续独立构建和跨Runtime A2A调用保留边界。

## 当前运行形态

当前保留根单Runtime兼容入口，同时新增可独立启动的`hr-consult-agent`本地A2A服务。两条入口共用同一个`build_consult_agent()`、提示词、Knowledge适配和工具清单，不存在第二份Consult实现。

```text
agent.py
├── build_employee_data_tools()
├── build_consult_agent(...)
├── build_leave_agent(...)
└── build_orchestrator(leave_agent, consult_agent, employee_data_tools)
    └── AgentkitAgentServerApp

python -m apps.consult_agent
└── 官方A2A JSON-RPC/SSE服务（127.0.0.1:8101）
    └── build_consult_agent(...)
```

根Orchestrator当前仍调用本地`hr_consult_agent`，尚未改为A2A消费者；该切换属于后续批次。当前没有云端Consult Runtime、A2A空间、语义发现或独立Employee Data Agent。请假Agent仍是Orchestrator的进程内能力。

## 目录职责

| 路径 | 当前职责 |
|---|---|
| `apps/orchestrator` | 根意图分流、页面跳转、JUMP回调、单Runtime装配接口 |
| `apps/orchestrator/local_leave` | 本地请假Agent、槽位收集、校验与请假单生成 |
| `apps/consult_agent` | 咨询Agent、独立A2A入口、文档解析、Knowledge工具和Viking适配 |
| `apps/employee_data_agent` | 本人余额、医疗期和年假折算工具的应用边界；尚无独立Agent |
| `apps/leave_agent` | 未来拆分门禁文档；没有可启动Agent |
| `packages/hr_domain` | 稳定领域常量、Schema、规则、Gaia客户端和响应适配 |
| `deployment` | 当前部署说明、资源清单模板和环境边界 |

`packages/hr_domain`可以承载与Agent框架无关的领域资产，不得包含Agent实例、提示词、`sub_agents`装配、AgentKit入口、A2A路由、Knowledge连接配置或对`apps`的反向导入。

## 本地验证

```bash
uv sync
uv run pytest -q
uv run pytest -q -m 'eval and not consult_eval' tests/eval/test_eval.py
uv run pytest -q -m consult_eval tests/eval/test_consult_eval.py
uv run python agent.py
uv run python -m apps.consult_agent
```

独立Consult的AgentCard地址为`http://127.0.0.1:8101/.well-known/agent-card.json`，JSON-RPC地址为`http://127.0.0.1:8101/`。环境变量参考[`.env.example`](.env.example)，部署与联调说明见[`deployment/README.md`](deployment/README.md)。
