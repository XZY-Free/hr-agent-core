你现在位于 hr-agent-core 当前工作区。

本轮只修改 hr-agent-core，不访问、不修改 SnowHarness 工作区。

请读取阶段2方案：

README.md
00-阶段2主控与并行编排.md
01-跨仓A2A集成合同冻结.md
02-HR-A2A端点与运行配置Authority.md
03-HR-A2A认证与ExecutionSubject身份边界.md
04-HR-Context-Resume-Cancel与结果语义.md
05-HR-注册工件-测试与Provider验收.md
09-回归-安全-最终只读审计.md
10-并行分支与合并纪律.md

目标：完成 Track H，使 hr-agent-core 成为与冻结跨仓合同完全自洽的真实黑盒 A2A Provider。

连续处理：

H1 Endpoint/Settings Authority
H2 Runtime Access Auth
H3 ExecutionSubject/identity boundary
H4 Context strict schema
H5 Resume identity continuity
H6 cancel=false official unsupported
H7 Registration artifacts
H8 Provider tests
H9 Live Provider smoke
H10 最终只读Track H审计

规则：

1. 当前工作区是唯一代码Authority，不checkout方案SHA。
2. 不修改SnowHarness。
3. 不重构Consult/Employee Data/Leave内部多Agent架构。
4. 不新增SnowHarness专属业务分支。
5. 不暴露employeeId。
6. 不实现durable recovery和cancel能力；false必须准确false。
7. 不用测试专用业务分支伪造input-required。
8. 不兼容旧execution_subject wire。
9. 新Authority建立后删除旧默认/旧artifact，不留legacy。
10. 每项完成后自行跑聚焦测试并继续，不等用户确认。
11. 最终必须启动真实Public A2A进程做live smoke。
12. 默认不push。

最终只回复：

TRACK_H_COMPLETE

或

TRACK_H_BLOCKED

并附HEAD、changed files、测试命令/结果、live endpoint/card/auth/lifecycle证据。

现在开始。
