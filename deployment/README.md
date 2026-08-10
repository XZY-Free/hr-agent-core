# 开发环境部署与本地联调

当前只完成本地多服务形态。新批次5任何云端写操作前，必须再次提交资源、规格、计费、凭据、部署顺序、回滚和线上影响清单，并等待项目负责人明确回复“允许开始云端部署”。

本批未运行`agentkit launch`，未创建或更新Runtime、A2A Space、A2A Agent、API Key、IAM角色或持续计费资源，现有线上`hr-agent`未修改。

## 1. 本地服务

| 服务 | 地址 | 启动命令 |
|---|---|---|
| Orchestrator | `http://127.0.0.1:8000` | `uv run python agent.py` |
| Consult A2A | `http://127.0.0.1:8101` | `uv run python -m apps.consult_agent` |
| Employee Data A2A | `http://127.0.0.1:8102` | `uv run python -m apps.employee_data_agent` |

Orchestrator的两种模式：

```bash
# 单Runtime兼容模式（默认）
HR_CONSULT_TRANSPORT=local \
HR_EMPLOYEE_DATA_TRANSPORT=local \
uv run python agent.py

# 本地三服务A2A模式
HR_CONSULT_TRANSPORT=a2a \
HR_EMPLOYEE_DATA_TRANSPORT=a2a \
uv run python agent.py
```

远端地址可通过`HR_CONSULT_A2A_URL`和`HR_EMPLOYEE_DATA_A2A_URL`配置；这两个变量只配置端点，不改变transport语义。

## 2. Consult服务端配置

| 变量 | 必填 | 说明 |
|---|---|---|
| `MODEL_AGENT_API_KEY` | 是 | 服务端模型Key |
| `KB_BACKEND` | 是 | 真实Viking使用`agentkit` |
| `KB_COLLECTION_POLICY` | 是 | policy collection |
| `KB_COLLECTION_HANDBOOK` | 是 | handbook collection |
| `KB_COLLECTION_SALARY` | 是 | salary collection |
| `KB_COLLECTION_CHILDCARE` | 是 | childcare collection |
| `VOLCENGINE_ACCESS_KEY` | 是 | 服务端AK，不写日志、Trace或Git |
| `VOLCENGINE_SECRET_KEY` | 是 | 服务端SK，不写日志、Trace或Git |
| `VOLCENGINE_SESSION_TOKEN` | STS时是 | 临时凭据token |
| `VIKING_KNOWLEDGE_HOST/REGION/SCHEME/PROJECT` | 按资源 | 官方SDK公开连接配置 |
| `LOGGING_LEVEL` | 是 | 使用`INFO`或更高等级 |

四个scope映射、`all`聚合、`top_k=5`和QPS重试保持不变。

## 3. Employee Data服务端配置

| 变量 | 必填 | 说明 |
|---|---|---|
| `MODEL_AGENT_API_KEY` | 是 | 服务端模型Key |
| `EMPLOYEE_IDENTITY_MAP_JSON` | 是 | A2A user_id到内部employeeId的可信映射 |
| `EMPLOYEE_REF_SECRET` | 是 | 生成不可逆employee_ref |
| `EMPLOYEE_DATA_BACKEND` | 是 | `gaia`或显式`stub`；不会自动回退 |
| `GAIA_CORP_ID` | Gaia时是 | 仅存在于Employee Data服务端 |
| `GAIA_CLIENT_SECRET` | Gaia时是 | 仅存在于Employee Data服务端 |
| `GAIA_GRANT_TYPE` | Gaia时是 | 仅存在于Employee Data服务端 |
| `EMPLOYEE_DATA_STUB_JSON` | Stub时是 | 本地测试数据；响应必须`source=stub` |

本地映射只用于验证两个明确测试身份的隔离，不代表企业SSO或AgentKit Identity已完成。A2A请求不得带`employeeId`、Gaia配置或任何密钥。

## 4. 本地接口验证

### 健康检查

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8101/health
curl -fsS http://127.0.0.1:8102/health
```

Employee Data健康响应示例：

```json
{"status":"ok","agent":"hr-employee-data-agent","version":"1.0.0"}
```

### AgentCard发现

```bash
curl -fsS http://127.0.0.1:8101/.well-known/agent-card.json
curl -fsS http://127.0.0.1:8102/.well-known/agent-card.json
```

业务调用必须使用官方A2A客户端，不在文档中手写JSONRPC请求。根会话、SSE和JUMP可用`scripts/local_client.py`验证；脚本不会替代真实A2A门禁。

## 5. 测试命令

```bash
# 本地/结构测试
uv run pytest -q

# local/local 21条
HR_CONSULT_TRANSPORT=local \
HR_EMPLOYEE_DATA_TRANSPORT=local \
uv run pytest -q tests/eval/test_eval.py -m eval

# 独立Agent
uv run pytest -q tests/eval/test_consult_eval.py -m consult_eval
uv run pytest -q tests/eval/test_employee_data_eval.py -m employee_data_eval

# 三服务a2a/a2a（需真实模型/Viking配置）
RUN_REAL_MULTI_AGENT_A2A_TESTS=true \
uv run pytest -q tests/e2e/test_local_multi_agent_a2a.py -m a2a_eval
```

完整结果和脱敏证据位置见`docs/local-multi-agent-a2a-report.md`。

## 6. 计划开发资源

`resource-inventory.example.yaml`只登记以下计划资源，当前均`created: false`：

```text
hr-orchestrator-dev
hr-consult-agent-dev
hr-employee-data-agent-dev
hr-agents-dev
hr-consult-agent
hr-employee-data-agent
```

新批次5获批前不得为名称冲突自动加随机后缀，不得创建生产资源，不得修改现有线上Runtime。规格、最小/最大实例数、是否持续计费、IAM/Secret、Runtime API Key、A2A鉴权、部署顺序和销毁方式目前均为待审批，不得从模板推断为已完成。

## 7. 云端部署前门禁

执行任何云端写操作前必须满足并提交：

1. 三个Runtime的地域、规格、最小/最大实例数和计费方式；
2. A2A Space及两个A2A Agent注册信息；
3. 复用资源、API Key、IAM角色和服务端Secret清单；
4. Employee Data真实身份提供方与Gaia凭据注入方式；
5. 部署顺序、回滚、销毁和现有线上`hr-agent`影响；
6. 本地完整测试报告；
7. 项目负责人明确回复“允许开始云端部署”。

未获批准时禁止`agentkit launch`、Runtime/A2A资源写操作、持续计费资源创建和云端删除。
