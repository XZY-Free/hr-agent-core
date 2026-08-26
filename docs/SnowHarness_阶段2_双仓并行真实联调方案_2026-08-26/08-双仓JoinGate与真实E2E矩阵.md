# 08 — 双仓 Join Gate 与真实 E2E 矩阵

## 1. Join 前置

必须同时获得：

```text
TRACK_H_COMPLETE
TRACK_S_COMPLETE
```

任一BLOCKED都不进入True E2E，也不在另一仓打补丁掩盖。

## 2. 只读核对

先记录：
```text
HR_HEAD
SNOWHARNESS_HEAD
git status
```

核对：
- protocol 0.3.0；
- AgentCard path；
- message/stream；
- metadata keys；
- execution_subject shape；
- same correlation resume；
- cancel=false；
- Artifact result。

不一致先回所属仓修复。

## 3. 真实运行环境

必须真正运行：
```text
MySQL 8
SnowHarness Web
SnowHarness必要workers
HR Public A2A Server
HR Agent真实Orchestrator runtime
```

如果HR内部Consult/Employee Data依赖真实远端A2A，完整矩阵使用实际配置，不能FakeServer替代最终Join。

## 4. Endpoint Smoke

从SnowHarness环境：
```text
GET HR /.well-known/agent-card.json
```

取card.url，必须等于Runtime Registration endpoint。

禁止人工改8000/8100绕过。

## 5. Contract Import

运营方将：
```text
hr-agent-core/artifacts/snowharness-registration/agent-contract.json
```

作为供应商交付的公共文件导入。

这不等于SnowHarness读取Provider源码。运行期SnowHarness不能依赖该repo。

## 6. E2E-01 Contract / Publication

真实：
```text
Register Contract
→ Snapshot
→ AgentRevision
→ Publish
```

断言0 source Artifact / Attestation。

## 7. E2E-02 Runtime Registration

live endpoint执行HR合同需要的：
```text
basic
input_required
resume
```

不包含cancel。

真实观察Card、SSE、input-required、same task/context resume、completed。

## 8. E2E-03 Authentication

阶段2正式验收跑两轮：

### none
基础本地链。

### bearer
HR启动bearer mode，SnowHarness CredentialRef引用对应secret。

断言：
- 正确credential PASS；
- 错credential FAIL；
- SnowHarness内部Workload Token不能调用HR endpoint；
- Secret不出双方日志。

## 9. E2E-04 Basic consultation

员工选择HR Agent：

```text
公司年休假的基本规则是什么？
```

要求：
- 不要求员工身份；
- A2A streaming transport；
- completed；
- 用户看到非空合理answer；
- DataPart正常处理。

不要求逐字答案。

## 10. E2E-05 Context

确认：
- execution subject来自SnowHarness服务端Principal；
- current_datetime合法；
- locale存在时为zh-CN；
- Provider收不到SnowHarness内部IDs。

不新增debug metadata dump endpoint。

## 11. E2E-06 Identity self-service

准备专用测试Principal。

HR operator私有配置：
```text
SnowHarness subject
→ pseudonymous internal_user_id
→ test employeeId
```

SnowHarness不知道employeeId。

真实请求例如：
```text
我还有多少年假？
```

要求真实identity mapping、Employee Data路径、response不泄露raw employeeId。

另跑未映射Principal：
- stable identity_unverified；
- 用户输入工号不能绕过。

## 12. E2E-07 Input-required / Resume

Start：
```text
我想请年假
```

预期input-required、UserAction、waiting_user、task/context持久化。

Resume：
```text
明天一天
```

必须：
- same Invocation；
- same Binding；
- same taskId；
- same contextId；
- same trusted subject；
- fresh current_datetime；
- completed或下一次合法input-required。

如还缺事由，可以继续Resume，每次same correlation。

## 13. E2E-08 cancel=false

- Web无Stop；
- Desktop无Stop；
- direct SnowHarness interrupt → unsupported；
- HR Provider没有tasks/cancel。

再用官方A2A client直接调用HR tasks/cancel：
- Provider返回unsupported；
- 不伪装cancelled。

## 14. E2E-09 Session continuity

同Thread第二个Turn：
- 复用HR contextId；
- 新Invocation；
- 新taskId；
- 不复用旧taskId。

## 15. E2E-10 Web ↔ Desktop

至少：
```text
Web创建真实HR Turn
→ Desktop读同Thread
```

并完成一次：
```text
一端waiting_user
→ 另一端Resume
→ 两端最终completed
```

## 16. E2E-11 Provider failure

停止HR Provider后发required Agent Turn：

- 不fallback base Harness；
- 按正式失败/queued/lost策略；
- UI不伪装回答；
- 不偷启a2a-test-provider。

## 17. E2E-12 Stream failure

连接建立后强制结束HR进程：

- 非terminal/non-waiting Invocation最终lost；
- SessionBinding lost；
- 不永久running。

## 18. Evidence

每项记录：
- PASS/FAIL；
- SnowHarness ids；
- taskId/contextId；
- terminal state；
- 是否真实网络；
- 是否用了mock。

核心E2E用了mock即FAIL。

## 19. Join完成

E2E-01～12全部满足适用条件后只能：
```text
JOIN_COMPLETE
```

“主要流程通了”不算。
