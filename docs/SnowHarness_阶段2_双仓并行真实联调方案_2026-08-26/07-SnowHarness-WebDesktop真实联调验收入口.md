# 07 — Track S2：SnowHarness Web / Desktop 真实联调验收入口

## 1. 目标

真实External Agent不能只API可调，必须从产品入口成立。

复用现有Playwright、Web/Desktop execution-chain，不重建E2E框架。

## 2. Live E2E开关

增加：
```text
SNOW_LIVE_EXTERNAL_AGENT_E2E=1
```

默认CI可skip live external tests。

阶段2 Join Gate显式开启，skip不算PASS。

## 3. Live E2E输入

只允许：
```text
LIVE_AGENT_CONTRACT_FILE
LIVE_AGENT_RUNTIME_ENDPOINT
LIVE_AGENT_AUTH_MODE
LIVE_AGENT_CREDENTIAL_REF_ID
LIVE_AGENT_BASIC_INPUT
LIVE_AGENT_INPUT_REQUIRED_INPUT
LIVE_AGENT_RESUME_INPUT
```

禁止source dir、Git SHA、employeeId、raw bearer token。

## 4. Admin UI E2E

至少一条Playwright真正点击：

```text
Resources
→ Register Contract
→ Snapshot
→ Create Revision
→ Publish AgentRevision
→ Register Runtime
→ Conformance
→ Publish RuntimeRevision
→ Route/Activation
```

不能API准备完后只打开页面。

## 5. Employee Web E2E

真实浏览器：
1. 新建会话；
2. Selector显示发布Agent；
3. 选择；
4. basic query；
5. 形成真实Agent Binding；
6. 显示Provider answer；
7. Thread不持久绑定Agent；
8. 后续仍是per-invocation selection。

## 6. input-required / Resume

```text
缺信息任务
→ UserAction/追问
→ 输入补充
→ same Invocation resume
→ completed
```

证据：
- same Invocation；
- same Binding；
- same taskId/contextId；
- no continuation Invocation；
- no Binding replacement。

## 7. cancel=false

页面不显示可点击Stop。

直接Interrupt API仍unsupported。

Provider无tasks/cancel。

不能只CSS隐藏。

## 8. Context

不为测试新增production metadata dump页。

通过现有Context Evidence/安全测试确认：
- subject来自login Principal；
- Resume same subject；
- current_datetime fresh；
- internal IDs不外发。

## 9. Desktop

Admin仍在Web。

Desktop员工侧验证：
1. Web/Admin完成发布；
2. Desktop加载Agent；
3. Desktop发真实消息；
4. answer；
5. input-required跨端可见；
6. 一端Resume，另一端看到completed。

复用cross-client和desktop execution chain。

## 10. Session continuity

至少：
```text
Web Start
→ A2A contextId
→ Desktop同Thread
→ 新Turn复用contextId
```

新Invocation taskId必须不同。

## 11. UI Error

Provider失败时员工看到稳定错误，不显示raw JSON-RPC stack、bearer或内部endpoint diagnostics。

## 12. Track S回归

继续跑normal Playwright、Web/desktop/cross-client/admin conformance、architecture gate、阶段1回归。

Live external真正连接HR留到Join Gate。

## 13. DoD

SnowHarness端具备：
```text
generic live runner
+ Studio live flow
+ Employee Web live flow
+ Desktop live flow
```

production 0 HR-specific branch。
