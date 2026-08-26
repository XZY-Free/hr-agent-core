# 05 — Track H4：HR 注册工件、测试与 Provider 验收

## 1. 目标

`artifacts/snowharness-registration` 只提供运营方公共输入和示例，不能成为第二Runtime Authority。

## 2. Agent Contract

保留 `agent-contract.json`，由生成器从正式 public_contract 生成。

测试必须比较：
- identity；
- capabilities；
- invocation_context；
- interaction；
- result contract。

禁止手工漂移。

## 3. 静态 Agent Card

当前 `agent-card.json` 容易被误当live authority。

改名：
```text
agent-card.example.json
```

只使用 `https://hr-assistant.example.invalid`。

删除旧 `agent-card.json`，不保留双文件兼容。

Runbook明确：live AgentCard只能HTTP discovery。

## 4. Runtime Registration Example

必须对齐阶段1 capability-driven schema。

HR Contract：
```text
streaming=true
incremental=false
inputRequired=true
resume=true
cancel=false
durable=false
```

因此example只含：

```text
conformance:
  basic:
    input
  input_required:
    input
  resume:
    start_input
    resume_input
```

绝不含cancel。

## 5. 固定示例输入

basic：
```text
公司年休假的基本规则是什么？
```

input_required：
```text
我想请假
```

resume start：
```text
我想请年假
```

resume：
```text
明天一天
```

静态示例必须有真实Provider test证明能产生预期状态，不能只写文件。

## 6. Auth Example

默认example `mode=none`。

Runbook单独说明bearer + SnowHarness CredentialRef，禁止提交假token字段。

## 7. snowharness-registration.md

重写为operator runbook：
1. 启动Public A2A；
2. health；
3. live AgentCard；
4. 导入agent-contract；
5. AgentRevision；
6. Runtime Registration；
7. Publication；
8. Route；
9. Employee选择；
10. input-required/resume；
11. cancel=false预期；
12. bearer可选配置。

不写SnowHarness内部源码路径。

## 8. `.env.example`

增加：
```text
HR_ASSISTANT_A2A_HOST=127.0.0.1
HR_ASSISTANT_A2A_PORT=8100
HR_ASSISTANT_A2A_PUBLIC_URL=http://127.0.0.1:8100
HR_ASSISTANT_A2A_AUTH_MODE=none
# HR_ASSISTANT_A2A_BEARER_TOKEN=
```

以及public subject mapping说明，不含真实凭据。

## 9. Provider Test Gate

至少：
```text
pytest -m "not eval"
```

并单独跑 public contract/runtime/A2A/local network/registration artifact相关测试。

环境具备时跑multi-agent A2A。

## 10. Live Provider Smoke

Track H结束前启动真实Public A2A进程，用官方A2A Client/真实HTTP验证：
1. health；
2. AgentCard；
3. basic message/stream；
4. input-required；
5. same task/context resume；
6. completed；
7. direct tasks/cancel → unsupported；
8. optional bearer；
9. 日志无secret。

这里只需要HR自身，不需要SnowHarness。

## 11. Track H输出

必须给：
```text
HEAD
changed files
public endpoint
AgentCard URL
auth tests
contract tests
lifecycle tests
pytest result
live provider smoke
```

只能 `TRACK_H_COMPLETE` 或 `TRACK_H_BLOCKED`。
