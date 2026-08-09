# HR Agent 单仓多应用工程

本仓库采用单仓多应用结构，让Orchestrator、制度咨询、员工本人数据和本地请假能力拥有明确代码归属，并为后续独立构建和跨Runtime A2A调用保留边界。

## 当前运行形态

批次2仍然只有一个AgentKit Runtime、一个服务入口和一套会话体系。根[`agent.py`](agent.py)是迁移期兼容装配入口：它构建员工数据工具集合、咨询Agent和本地请假Agent，再显式注入Orchestrator。应用目录之间不导入其他应用的Agent实例。

```text
agent.py
├── build_employee_data_tools()
├── build_consult_agent(...)
├── build_leave_agent(...)
└── build_orchestrator(leave_agent, consult_agent, employee_data_tools)
    └── AgentkitAgentServerApp
```

当前没有A2A调用、AgentCard、语义发现或独立子Runtime。咨询Agent将在批次3形成独立Agent与Runtime，员工数据Agent将在批次4形成独立Agent与Runtime。请假Agent本批仍是Orchestrator的进程内能力。

## 目录职责

| 路径 | 当前职责 |
|---|---|
| `apps/orchestrator` | 根意图分流、页面跳转、JUMP回调、单Runtime装配接口 |
| `apps/orchestrator/local_leave` | 本地请假Agent、槽位收集、校验与请假单生成 |
| `apps/consult_agent` | 咨询Agent、文档解析、Knowledge工具和Viking适配 |
| `apps/employee_data_agent` | 本人余额、医疗期和年假折算工具的应用边界；尚无独立Agent |
| `apps/leave_agent` | 未来拆分门禁文档；没有可启动Agent |
| `packages/hr_domain` | 稳定领域常量、Schema、规则、Gaia客户端和响应适配 |
| `deployment` | 当前部署说明、资源清单模板和环境边界 |

`packages/hr_domain`可以承载与Agent框架无关的领域资产，不得包含Agent实例、提示词、`sub_agents`装配、AgentKit入口、A2A路由、Knowledge连接配置或对`apps`的反向导入。

## 本地验证

```bash
uv sync
uv run pytest -q
uv run pytest -q -m eval
uv run python agent.py
```

环境变量参考[`.env.example`](.env.example)，部署与联调说明见[`deployment/README.md`](deployment/README.md)。
