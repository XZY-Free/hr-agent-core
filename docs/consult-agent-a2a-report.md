# 批次3 Consult Agent本地A2A报告

状态：本地实现与门禁完成

检查时间：2026-08-09（Asia/Shanghai）

起点提交：`2168217 refactor: organize hr agent as multi-application monorepo`

## 1. 结果与边界

本批建立了可独立启动的`hr-consult-agent`本地A2A服务，根单Runtime继续使用同一个`build_consult_agent()`作为本地子Agent。独立Consult只装配`kb_search`和`parse_document`，构建接口不再接收`employee_data_tools`。

根Orchestrator尚未改为A2A消费者；Employee Data与Leave没有拆分；没有执行`agentkit launch`，没有创建或修改Runtime、A2A Agent、A2A Space及其他云资源。

## 2. 实现依据

| 项目 | 锁定值 |
|---|---|
| AgentKit SDK | `agentkit-sdk-python==0.8.1` |
| veADK | `veadk-python==1.1.0` |
| google-adk | `2.2.0` |
| 官方A2A SDK | `a2a-sdk[http-server]==0.3.7` |
| A2A协议 | `0.3.0` |
| Transport | `JSONRPC` |

服务端使用官方公开`A2AFastAPIApplication`、`DefaultRequestHandler`、`AgentExecutor`、`TaskUpdater`和`InMemoryTaskStore`；客户端验证使用官方公开`A2ACardResolver`、`ClientFactory`与SDK的`Message`、`Task`、`Artifact`、`TextPart`、`DataPart`模型。没有访问下划线私有成员，没有复制协议实现或手写JSON-RPC路由。

## 3. 独立入口与配置

入口为`python -m apps.consult_agent`，固定监听`127.0.0.1:8101`：

| 接口 | 地址 | 本批结果 |
|---|---|---|
| 健康检查 | `http://127.0.0.1:8101/health` | HTTP 200 |
| AgentCard | `http://127.0.0.1:8101/.well-known/agent-card.json` | HTTP 200，官方Resolver解析通过 |
| JSON-RPC/SSE | `http://127.0.0.1:8101/` | 非流式与流式均通过 |

必要配置为模型Key、`KB_BACKEND=agentkit`、四个collection映射、Viking AK/SK及按资源需要提供的endpoint、region、scheme、project、STS token。配置检查不要求员工身份、Gaia endpoint、`corp_id`、`client_secret`或`grant_type`，缺少必要collection时明确失败。

## 4. AgentCard

```yaml
name: hr-consult-agent
description: 回答人力制度、政策、考勤、薪酬福利、系统操作和文档内容问题；不查询员工本人数据，不办理请假
version: 1.0.0
protocolVersion: 0.3.0
preferredTransport: JSONRPC
url: http://127.0.0.1:8101/
capabilities:
  streaming: true
defaultInputModes: [text]
defaultOutputModes: [text]
provider:
  organization: HR Agent Team
  url: http://127.0.0.1:8101
```

| Skill ID | 名称 | 作用 |
|---|---|---|
| `hr-policy-consultation` | 人力制度咨询 | 考勤、休假、入离职、试用期制度问答 |
| `hr-benefit-consultation` | 薪酬福利咨询 | 薪酬、津贴、福利问答 |
| `hr-system-operation-guide` | 人事系统操作指引 | 人事系统和操作手册问答 |
| `hr-document-question-answering` | 人力文档问答 | 解析人力文档链接并回答内容 |

这些skills只是A2A能力声明，不代表已接入AgentKit Skill平台资源。

## 5. 请求、Task与Artifact

请求metadata严格只接受`request_id`、`user_id`、`session_id`、`caller_agent=hr_orchestrator`、`locale=zh-CN`和`context_summary`；问题正文放在官方`TextPart`。未知字段、字段缺失、上下文与session不一致或敏感凭据标记均在进入Agent前失败。

成功和业务失败都通过官方Task与Artifact表达。Artifact包含面向用户的`TextPart`及机器可读`DataPart`：

```json
{
  "request_id": "<原样透传>",
  "status": "succeeded",
  "answer": "<面向用户的回答>",
  "question_category": "hr_policy",
  "knowledge_scope": "policy",
  "sources": [{"source": "<Viking原始文档名>", "score": "<Viking原始浮点分数>"}],
  "truncated": false,
  "recommend_hr": false,
  "agent_name": "hr-consult-agent",
  "agent_version": "1.0.0",
  "error_code": null
}
```

Knowledge切片正文不进入Artifact。`score=0`由契约测试证明不会丢失。

## 6. 固定本地A2A用例

测试启动真实`127.0.0.1:8101`服务并使用官方客户端走网络协议，结果为`14 passed`。其中12个冻结用例如下：

| 用例 | 结果 | 关键证据 |
|---|---|---|
| 迟到扣款制度 | `succeeded` | scope=`policy`，真实source/score存在 |
| 四川育儿假 | `succeeded` | scope=`childcare`，回答含10天，真实来源存在 |
| 育儿假缺省份 | `need_more_information` | 追问地区，不调用Knowledge |
| 餐补标准 | `succeeded` | scope=`salary`，真实来源存在 |
| 人事系统考勤操作 | `succeeded` | scope=`handbook`，基于真实检索 |
| 本人年假余额 | `rejected` | `personal_data_not_allowed`，无Gaia工具、无个人数字 |
| 请假办理 | `rejected` | `leave_request_not_allowed` |
| IT报修 | `rejected` | `out_of_scope` |
| 火星基地宠物报销 | `not_found` | `knowledge_not_found`，未用低质量召回拼答案 |
| Knowledge故障注入 | `temporarily_unavailable` | `knowledge_network_error`，Task为failed，与无结果不同 |
| 文档链接问答 | `succeeded` | 使用`parse_document`，未调用Knowledge |
| 缺少必要字段 | 协议错误 | 官方客户端收到invalid params，不以默认身份执行 |

额外协议门禁验证了四个Skill、非流式、SSE事件正常结束、`request_id`透传、两个session隔离、同一上下文首轮追问省份后补充“四川”成功、服务地址不可用时官方客户端明确连接失败。

脱敏机器证据：`tests/e2e/logs/consult-a2a-real-20260809-193111.jsonl`（本地保留、Git忽略）；断言实现：`tests/e2e/test_consult_a2a_real.py`和`tests/e2e/test_consult_a2a_protocol.py`。

## 7. 评测与回归

| 门禁 | 结果 | 证据 |
|---|---|---|
| 独立Consult 10条评测 | 10 passed | `tests/eval/logs/consult-eval-20260809-192712.jsonl` |
| 原根入口21条核心评测 | 21 passed | `tests/eval/logs/eval-20260809-192825.log` |
| 非阻塞推荐追问 | 独立Consult命中、根入口未命中；两者核心事实均通过 | 上述两份评测日志 |
| 非评测测试 | 154 passed，19 skipped，31 deselected | 全量本地pytest输出；真实跳过项由下列独立门禁覆盖 |
| 真实Viking集成 | 5 passed | `tests/integration/test_viking_knowledge.py` |
| 真实本地A2A | 14 passed | `tests/e2e/test_consult_a2a_real.py` |
| 根单Runtime健康 | HTTP 200 | 本批本地HTTP输出 |
| 根会话创建 | HTTP 200 | 本批本地HTTP输出 |
| 根SSE | HTTP 200，13个事件 | 本批本地HTTP输出 |
| JUMP | `[[JUMP:punch-details]]`完整保留 | 本批本地HTTP输出 |
| 独立Consult健康 | HTTP 200 | 本批本地HTTP输出及协议测试 |

原21条用例和业务断言未删除或修改。独立10条不再断言根Agent的transfer，而是检查Consult职责、工具、scope、真实来源和关键事实。`kb_empty_honest`保留原基线允许的两种正确路径：检索后无结果，或直接识别非人力并拒答；本次走后者并返回`rejected/out_of_scope`。

## 8. 安全与观测

本地日志只记录`request_id`、调用方、目标Agent、版本、状态、耗时、Knowledge scope、工具名和错误码，不记录问题正文、Knowledge切片、提示词、身份数据、认证头或密钥。veADK默认DEBUG会输出完整工具响应，因此独立入口在导入veADK前将未显式配置的日志等级收紧到INFO；fresh-process回归测试证明DEBUG正文不会输出。

请求允许列表和敏感标记过滤覆盖`client_secret`、Authorization/Bearer、AK/SK、模型Key、Runtime API Key和Gaia JWT。Artifact固定模型没有凭据字段，Knowledge正文不进入DataPart。真实A2A证据日志只记录状态、scope和来源数量。

本地未启用远端Trace exporter，因此没有把本地日志结果冒充云端Trace验证。跨Runtime request ID/Trace、AgentKit控制台A2A观测、Token聚合、云端错误分析和平台Knowledge分析关联均未验证，留待获批部署后的批次。

## 9. 未验证项与遗留问题

- 真实Gaia、持久Session、Runtime重启、多实例会话一致性、跨Runtime A2A与Trace未验证。
- AgentKit Skill、Identity、MCP、Memory专题未在本批实施；AgentCard skills只表示A2A能力。
- 批次0记录的JWT缓存、敏感字段进入根`session.state`、导入时日期冻结等问题保持原状。
- A2A本地服务当前使用内存Task/Session，云端持久性与多实例行为尚未验证。

## 10. 与冻结方案的偏差

无核心偏差。锁文件已包含`a2a-sdk==0.3.7`，本批把官方`http-server` extra提升为直接依赖以声明实际服务端能力；AgentKit与veADK没有可复用的公开A2A服务适配，因此使用官方A2A SDK公开接口。为使独立Consult不导入Orchestrator，批次2的模型配置文件按原内容迁到`packages/agent_runtime/model_config.py`，根入口同步引用；模型名、thinking逻辑和默认值未改变。
