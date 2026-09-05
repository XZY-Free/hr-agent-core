# Consult Agent 应用

`hr_consult_agent` 负责人力制度、政策、考勤、薪酬福利、系统操作和文档问答。它不查询员工本人数据、不办理请假，也不依赖 Orchestrator 或 Gaia。工具装配见仓库源码 `apps/consult_agent/agent.py`。

## 远端服务

Consult 以独立 A2A 服务部署在云 Runtime（当前版本 v14，`KB_BACKEND=agentkit`，四个 collection 已配置；当前镜像 `agentkit-platform-2101533667-cn-beijing.cr.volces.com/agentkit/hr-agent-vkba:ec927bc-wp07-final-attendance-aff56a4e32c8`）。不再被生产 Orchestrator 作为本地子 Agent 装配。健康检查与 AgentCard 发现由 AgentKit 远端验收客户端在 `tests/agentkit` 下执行，不在本手册给出 localhost curl 演示。

## 服务端配置

独立服务需要模型 Key、`KB_BACKEND=agentkit`、四个 collection 映射和 Viking 服务端 AK/SK；`VIKING_KNOWLEDGE_HOST/REGION/SCHEME/PROJECT` 按资源配置，可选项为空时使用官方 SDK 自身默认值，应用代码不硬编码。它不接收 `employeeId`、Gaia 配置或根 session state。

`policy`、`handbook`、`salary`、`childcare` 映射、`all` 语义、`top_k=5`、QPS 重试和 Viking 官方公开 SDK 保持不变。Knowledge 响应保留真实 `content/source/score`；A2A Artifact 只带受控来源和分数，不带切片正文。

## 验收口径

当前验收入口是 `tests/agentkit` 下对已部署 Consult Runtime 的远端 HTTP 客户端用例；模型/Knowledge 在 AgentKit 服务端，测试不能注入 session state 伪造业务事实。详见 [`../../docs/agentkit-acceptance.md`](../../docs/agentkit-acceptance.md)。
