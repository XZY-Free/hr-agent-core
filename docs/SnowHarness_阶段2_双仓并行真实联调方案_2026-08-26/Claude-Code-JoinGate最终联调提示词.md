现在进入 SnowHarness 阶段2 Join Gate。

前置必须已有：

TRACK_H_COMPLETE
TRACK_S_COMPLETE

缺任一项立即停止。

本次可以分别打开两个工作区执行命令/查看代码，但修复必须回问题所属仓：
- Provider问题 → hr-agent-core
- Consumer问题 → SnowHarness

禁止在另一仓加特例。

严格读取：

00-阶段2主控与并行编排.md
01-跨仓A2A集成合同冻结.md
08-双仓JoinGate与真实E2E矩阵.md
09-回归-安全-最终只读审计.md

按顺序：

1. 两仓HEAD/status。
2. 只读核对跨仓合同。
3. 启动真实MySQL、SnowHarness、workers。
4. 启动真实hr-agent-core Public A2A Provider。
5. Agent Card endpoint一致性。
6. 导入真实agent-contract.json。
7. AgentRevision/Publication。
8. Runtime Registration真实Conformance。
9. Runtime Publication + Route。
10. none auth链。
11. bearer auth链。
12. Web basic consultation。
13. identity self-service。
14. input-required/resume。
15. cancel=false。
16. session continuity。
17. Web/Desktop cross-client。
18. Provider停止/恢复。
19. stream中断 → lost。
20. 两仓全量回归。
21. Secret/source-opacity/Architecture Gate。
22. 最终只读审计。

核心E2E禁止：
- SnowHarness a2a-test-provider；
- FakeServer；
- mock HR runtime；
- 直接DB制造状态。

真实外部Key缺失可以让对应业务资源用例HARD_BLOCKED，但不能改用mock后宣布COMPLETE。

最终只能：

COMPLETE

或

HARD_BLOCKED

并按09文档输出完整证据。
