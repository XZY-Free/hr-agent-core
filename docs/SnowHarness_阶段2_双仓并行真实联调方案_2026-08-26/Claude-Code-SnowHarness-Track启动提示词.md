你现在位于 SnowHarness 当前工作区。

本轮只修改 SnowHarness，不访问、不修改 hr-agent-core。

读取：

README.md
00-阶段2主控与并行编排.md
01-跨仓A2A集成合同冻结.md
06-SnowHarness-LiveExternalAgent通用联调能力.md
07-SnowHarness-WebDesktop真实联调验收入口.md
09-回归-安全-最终只读审计.md
10-并行分支与合并纪律.md

第一件事不是写代码，而是验证阶段1是否 COMPLETE。

逐项检查：
- AgentRevision无source Authority；
- Runtime Registration capability-driven；
- External Credential接线；
- Context Enrichment接线；
- cancel=false贯通；
- A2A stream recovery；
- Studio管理闭环；
- 阶段1Architecture Gate。

若未完成：
返回 `TRACK_S_BLOCKED_BY_STAGE1`，列精确缺口，不做HR特例补丁。

若COMPLETE，继续：

S1 Generic Live External Agent Runner
S2 Runner只走正式控制面API/worker
S3 live E2E环境合同
S4 Admin Studio live E2E
S5 Employee Web live E2E
S6 Desktop/Cross-client live E2E
S7 no-HR-special-case Gate
S8 SnowHarness全量回归
S9 最终只读Track S审计

规则：

1. production禁止hr-assistant/HR Agent/8100/veADK/AgentKit行为特例。
2. Provider永远源码不可见。
3. 不读Provider Git、源码目录、Python包。
4. Runner只接contract file + endpoint + CredentialRef +测试输入。
5. 不直接写DB制造Publication/Projection/Binding/Invocation。
6. required Agent失败不fallback base Harness。
7. Live test默认可skip，但Join必须真跑。
8. 不修改hr-agent-core。
9. 默认不push。

最终只回复：

TRACK_S_COMPLETE

或

TRACK_S_BLOCKED_BY_STAGE1 / TRACK_S_BLOCKED

附HEAD、changed files、测试命令/结果。

现在开始。
