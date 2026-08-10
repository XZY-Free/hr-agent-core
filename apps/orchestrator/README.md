# Orchestrator应用

`hr-orchestrator`负责固定意图路由、本地Leave、页面跳转/JUMP、取消引导、人工入口和两个A2A消费者。它不直接查询Knowledge或员工本人数据。

## 固定路由

| 优先级 | 意图 | 目标 |
|---|---|---|
| 1 | 请假申请、修改、请假多轮 | 本地Leave |
| 2 | 取消、撤回 | 本地页面引导 |
| 3 | 本人余额、医疗期、工龄、年假折算 | Employee Data |
| 4 | 打开页面 | 本地`page_jump` |
| 5 | 制度、福利、系统操作、文档 | Consult |
| 6 | 人工服务 | 本地人工入口 |
| 7 | 闲聊 | 本地Orchestrator |

远端目标由确定性规则选择，不由模型自由选择。本批不使用A2A Space语义发现。

## Transport

| 变量 | 默认值 | 允许值 |
|---|---|---|
| `HR_CONSULT_TRANSPORT` | `local` | `local`、`a2a` |
| `HR_EMPLOYEE_DATA_TRANSPORT` | `local` | `local`、`a2a` |

端点分别由`HR_CONSULT_A2A_URL`和`HR_EMPLOYEE_DATA_A2A_URL`配置，默认是`http://127.0.0.1:8101`和`http://127.0.0.1:8102`。端点变量不是第三个transport开关。

远端请求只发送`request_id/user_id/session_id/caller_agent/locale/message/context_summary`。不发送完整session、提示词、历史、employeeId或任何密钥。A2A失败返回目标专用安全话术，不走本地静默兜底。

根入口由仓库`agent.py`装配并监听`127.0.0.1:8000`（直接运行时监听`0.0.0.0:8000`）。
