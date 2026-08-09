# 批次2单仓多应用重组报告

状态：本地重组与门禁完成

检查时间：2026-08-09（Asia/Shanghai）

起点提交：`6ecca1e chore: upgrade agentkit and veadk dependencies`

## 1. 结果

本批把原`hr_agent`单体目录按职责迁入`apps`和`packages/hr_domain`，根`agent.py`继续作为唯一兼容装配入口。运行时仍是一个进程、一个`AgentkitAgentServerApp`、一套内存会话服务，Consult与Leave仍通过本地`sub_agents`执行。

本批没有创建独立Runtime、AgentCard、A2A客户端、A2A空间或语义发现，也没有执行云端写操作。

## 2. 当前装配链

```text
agent.py
├── apps.employee_data_agent.build_employee_data_tools()
├── apps.orchestrator.local_leave.build_leave_agent(...)
├── apps.consult_agent.build_consult_agent(employee_data_tools=...)
└── apps.orchestrator.build_orchestrator(
      leave_agent=...,
      consult_agent=...,
      employee_data_tools=...,
    )
    └── AgentkitAgentServerApp(root_agent, ShortTermMemory(local))
```

只有根`agent.py`构造Agent实例并完成跨应用依赖注入。应用模块提供构建函数，不反向导入根入口，也不导入其他应用的Agent实例。

## 3. 迁移映射

| 旧模块 | 新模块 | 职责 |
|---|---|---|
| `hr_agent/agents/main_agent.py` | `apps/orchestrator/agent.py` | 根Agent构建 |
| `hr_agent/agents/consult_agent.py` | `apps/consult_agent/agent.py` | 咨询Agent构建 |
| `hr_agent/agents/leave_agent.py` | `apps/orchestrator/local_leave/agent.py` | 本地请假Agent构建 |
| `hr_agent/agents/prompts.py` | `apps/orchestrator/prompts.py`、`apps/orchestrator/local_leave/prompts.py`、`apps/consult_agent/prompts.py` | 按应用归属原样迁移三个提示词 |
| `hr_agent/agents/model_config.py` | `apps/orchestrator/deployment/model_config.py` | 单Runtime模型环境装配 |
| `hr_agent/callbacks/jump_marker.py` | `apps/orchestrator/callbacks/jump_marker.py` | JUMP回调 |
| `hr_agent/constants/page_codes.py` | `packages/hr_domain/constants/page_codes.py` | 页面码表纯数据 |
| `hr_agent/constants/leave_rules.py` | `packages/hr_domain/constants/leave_rules.py` | 请假规则常量 |
| `hr_agent/constants/phrases.py` | `packages/hr_domain/constants/phrases.py` | 固定业务话术数据 |
| `hr_agent/schemas/leave_form.py` | `packages/hr_domain/schemas/leave_form.py` | 请假单Schema |
| `hr_agent/schemas/tool_result.py` | `packages/hr_domain/schemas/tool_result.py` | 统一工具结果模型 |
| `hr_agent/tools/rules/annual_leave.py` | `packages/hr_domain/rules/annual_leave.py` | 年假折算规则 |
| `hr_agent/tools/rules/leave_dates.py` | `packages/hr_domain/rules/leave_dates.py` | 请假日期推算 |
| `hr_agent/tools/rules/page_jump.py` | `apps/orchestrator/routing/page_jump.py` | 页面跳转工具 |
| `hr_agent/tools/rules/kb_search.py` | `apps/consult_agent/tools/kb_search.py` | Knowledge工具与scope选择 |
| `hr_agent/tools/rules/parse_document.py` | `apps/consult_agent/tools/parse_document.py` | 文档解析 |
| `hr_agent/tools/gaia/client.py` | `packages/hr_domain/gaia/client.py` | Gaia HTTP/JWT客户端 |
| `hr_agent/tools/gaia/employee_query.py` | `packages/hr_domain/gaia/employee_query.py` | 员工信息与医疗期查询 |
| `hr_agent/tools/gaia/leave_query.py` | `packages/hr_domain/gaia/leave_query.py` | 权限与余额查询 |
| `hr_agent/tools/gaia/schedule_query.py` | `packages/hr_domain/gaia/schedule_query.py` | 排班查询 |
| `hr_agent/tools/gaia/submit.py` | `apps/orchestrator/local_leave/submit.py` | 请假单生成与既有提交边界 |
| `hr_agent/knowledge/backend.py` | `apps/consult_agent/knowledge/backend.py`、`types.py` | Knowledge抽象、工厂和类型 |
| `hr_agent/knowledge/agentkit_backend.py` | `apps/consult_agent/knowledge/agentkit_backend.py` | Viking官方SDK适配 |
| `hr_agent/knowledge/local_stub.py` | `apps/consult_agent/knowledge/local_stub.py` | 本地Knowledge Stub |
| `hr_agent/knowledge/fixtures/*` | `apps/consult_agent/knowledge/fixtures/*` | 本地Stub文档 |
| `tests/test_*.py` | `tests/unit/test_*.py` | 原非评测测试，断言不变 |
| `tests/fixtures/notice.md` | `tests/unit/fixtures/notice.md` | 文档解析测试夹具 |
| `deploy/README.md` | `deployment/README.md` | 部署与联调说明 |

`apps/employee_data_agent/agent.py`新增当前进程内的本人数据工具集合构建边界；它不实例化独立Agent。`apps/leave_agent`只包含未来拆分说明和`SPLIT-GATE.md`，当前请假实现仍位于`apps/orchestrator/local_leave`。

## 4. 依赖方向

```text
根 agent.py
  ├── apps/orchestrator
  ├── apps/consult_agent
  └── apps/employee_data_agent
          │
          ▼
   packages/hr_domain
```

- `apps`之间没有直接导入；跨应用实例只由根入口构造和注入。
- `packages/hr_domain`不依赖`apps`、veADK或AgentKit，不含提示词和Agent实例。
- Knowledge配置和实现只位于`apps/consult_agent`。
- 页面路由和JUMP回调只位于`apps/orchestrator`。
- 本地Leave可以直接使用`hr_domain`的Gaia与规则实现，不经未来Employee Data Agent绕行。

结构测试对上述方向、循环依赖、工具顺序、提示词哈希、21条评测数量和旧目录删除进行门禁。

## 5. 删除与兼容入口

删除整个旧`hr_agent`包及其`agents`、`callbacks`、`constants`、`knowledge`、`schemas`、`tools`实现；没有保留转发模块或第二份业务实现。旧`deploy`路径和旧测试路径同时删除。

保留仓库根`agent.py`作为当前AgentKit加载兼容入口，原因是批次2必须保持现有单Runtime外部加载方式。计划在批次7删除其中的本地Consult与Employee Data装配职责，并由完成开发环境验证的正式Orchestrator入口接管；本批不提前实施。

## 6. 行为与测试证据

| 验证 | 结果 | 证据 |
|---|---|---|
| 非评测单元与结构测试 | 118 passed | `tests/unit`、`tests/contract`本批输出 |
| 结构门禁独立复跑 | 8 passed | `tests/contract/test_monorepo_structure.py`本批输出 |
| 真实Viking Knowledge | 5 passed | `tests/integration/test_viking_knowledge.py`本批输出 |
| 真实模型核心业务评测 | 21 passed，123 deselected | `tests/eval/logs/eval-20260809-170417.log` |
| 非阻塞质量指标 | `recommended_followup`本次命中；核心业务通过 | 同上日志第264至276行 |
| 健康检查 | HTTP 200，`{"status":"ok"}` | 本批本地HTTP输出 |
| 会话创建 | HTTP 200 | 本批`local_client.py`与服务日志 |
| SSE | 两次HTTP 200且收到模型事件 | 本批`local_client.py`与服务日志 |
| JUMP | 完整保留`[[JUMP:punch-details]]` | 本批`local_client.py`输出 |
| 依赖锁 | `uv lock --check`通过 | 本批命令输出 |
| SDK私有成员扫描 | 通过 | 本批`rg`扫描输出 |
| 差异格式 | `git diff --check`通过 | 本批命令输出 |

行为对比覆盖Orchestrator、本地Leave、Consult、本人数据和页面JUMP。21条评测继续验证路由目标、必要工具、关键事实、Knowledge来源与score；结构测试固定三个Agent的工具名称与顺序。提示词内容由重组前SHA-256固定，模型配置与批次1文件逐字节一致。

## 7. 未验证项与遗留问题

- 真实Gaia凭据与真实员工数据未验证；本地SSE沿用dummy凭据验证既有失败分类，不冒充真实Gaia结果。
- 持久会话、Runtime重启、多实例会话一致性、跨Runtime A2A和跨Runtime Trace尚未实施。
- AgentKit平台对官方Viking SDK自定义Trace的远端展示尚未验证。
- 批次0记录的JWT缓存跨工具复用、敏感字段进入`session.state`、日期在模块导入时冻结等问题保持原状，本批未修复。

## 8. 与冻结方案的偏差

无核心偏差。固定目录图中的`apps/employee_data_agent/prompts.py`、`packages/hr_domain/contracts`和`packages/hr_domain/errors`没有现有实现可迁移，本批按“只创建确实需要承载内容的模块”要求未创建空占位代码。Employee Data正式提示词、独立Agent和A2A结构化契约仍分别留在冻结的后续批次。
