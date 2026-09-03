# HR 交互与 Web 验证现状

日期：2026-08-28。用户明确：HR 智能体的 AI 决定，SnowHarness 展示和回传；本次只验收 Web。

## 当前实现

| 行为 | 实现与边界 |
| --- | --- |
| 请求业务信息 | HR AI 调用 request_user_input（请求用户输入），Runner读取明确工具事件，公开服务返回input-required（等待输入） |
| 普通答案 | 问候、完整答案和推荐追问保持正常文本，不用关键词、问号或省名推断卡片 |
| 同任务回填 | SnowHarness带原task/context（任务/上下文）回传，HR恢复该任务；本地任务保留原路由 |
| 取消 | 官方tasks/cancel使用params.id；等本地工作退出与下游停止确认才返回canceled（已取消） |
| 后台配置缺失 | 返回无法办理，不向员工索取企业ID、员工ID、访问令牌或密码 |

例如“我想请年假”缺日期和事由时，AI明确调用工具；“你好”“深圳育儿假”的已完成答案不会因为含有“告诉我”、推荐问题或业务词而变成回填卡片。

取消不撤销已完成副作用；同步工具执行期间只能等待其返回，不能强杀已经发出的外部业务请求。进程重启后的任务恢复仍不支持。

## 真实验证

- 公开HR服务及本地Consult服务调用真实模型和知识库，SnowHarness使用真实开发MySQL；没有录制Runtime替代页面验收。
- Web重新导入合同、发布智能体、登记运行地址、能力验收、发布给员工成功；运行版本`7487afa5-a8a2-4299-987f-64b018fe2e7d`，验收`019fb805-9ed4-4940-8814-3de6b3f8c619`通过。
- Web问候、深圳育儿假查询正常，无补充请求。
- 缺信息→回填“明天”→继续提问沿用任务`3d99c165-a703-438f-b12f-ea2a4fc1f94c`；再取消后任务停止，旧卡已提交、新卡已取消，刷新一致。
- 360px页面真实运行取消，任务`3531d9e8-98fd-43d6-be94-5bf4fd88d8b8`通过官方tasks/get确认canceled、0个结果；页面刷新无迟到答案。
- 代码验证：`uv run pytest -q tests/unit tests/contract tests/e2e/test_hr_assistant_a2a_protocol.py`，395通过。真实HTTP协议测试使用临时端口，不占用本地运行服务端口。

详细页面证据及查询命令保存在SnowHarness的`docs/verification/hr-web-2026-08-28.md`。

## 注册资料

公开合同当前声明：streaming=true（事件流）、input_required=true（等待输入）、resume=true（恢复）、cancel=true（取消）；incremental_content=false（无逐字增量正文）、durable_task_recovery=false（无重启恢复）。

`scripts/generate_snowharness_registration.py`生成更新后的注册资料。操作者将合同导入平台，平台按字段和子表保存；平台不读HR源码或内部合同目录，不通过运行地址拉取公共合同。AgentCard仅用于协议端点和能力一致性核对。

## 未完成项

业务请假办理缺少HR后台身份与服务配置，实际完整信息检查返回余额查询不可用；未提交请假单，不能记为业务办理成功。Employee Data本地服务未启动。桌面端本次不验收。尚不能升级通用规范v1.0或产出通用Skill。
