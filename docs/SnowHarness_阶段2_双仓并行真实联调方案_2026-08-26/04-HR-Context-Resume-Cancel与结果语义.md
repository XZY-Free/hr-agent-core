# 04 — Track H3：HR Context / Resume / cancel=false / Result 语义

## 1. 目标

让 HR Public Provider 对阶段 2 冻结 wire 严格自洽，不重构 HR 内部业务 Agent。

## 2. Public Request Context Schema

当前 `context: dict` 必须收紧为明确结构：

```text
timezone?: string
current_datetime?: string
locale?: string
conversation_summary?: string
attachment_references?: list[AttachmentReference]
```

`execution_subject` 独立字段，未知 Context key一律拒绝。

## 3. AttachmentReference

固定：

```text
reference_id: non-empty string
resource_type: non-empty string
display_name?: string
media_type?: string
```

extra=forbid。

禁止 path / file:// / access_token / secret / raw_content。

阶段2 Public Runtime只把这些当外部引用，不负责读取SnowHarness资源。未来若要取附件，走正式Connector/Gateway，不在本阶段做。

## 4. current_datetime

- 必须ISO 8601；
- 非法字符串 → contract_error；
- 缺失 → Provider当前时间；
- 每次invoke重新确定。

禁止“传错了就静默fallback”。

## 5. timezone

如果提供：
- 非空；
- 必须是ZoneInfo可解析的IANA timezone；
- 非法 → contract_error。

缺失时HR可默认 `Asia/Shanghai`，但该默认只是HR内部业务事实。

## 6. locale

只允许 `zh-CN`，其他 → contract_error。

## 7. Context如何进入业务

本阶段现有local path至少使用 `current_datetime + timezone` 形成执行上下文。

不要把 execution_subject、附件引用、SnowHarness内部ID直接拼Prompt。

conversation_summary如果存在：
- 独立“历史摘要”区块；
- 与用户正文分隔；
- 不能覆盖system prompt；
- 不能当trusted instruction执行。

attachment refs没有正式消费者时保持结构化，不把JSON硬塞Prompt。

## 8. Resume

Executor继续使用官方 `context.current_task` 判断同一Task Resume。

禁止新Task替代Resume、taskId/contextId变化。

Public Runtime：
- execution_subject每次重新解析；
- session_id=context_id；
- continuation只属于exact `(context_id, task_id)`。

## 9. In-memory continuation

当前 `_pending_local_continuations` 可以保留，因为 Contract `durable_task_recovery=false`。

必须：
- 同进程准确；
- terminal/failed清除；
- 不跨context/task串线；
- 不宣称durable。

## 10. input-required

继续使用正式A2A `requires_input` 状态，SnowHarness必须收到taskId/contextId和追问文本。

禁止只返回completed文本“请补充xxx”。

## 11. local missing-info heuristic约束

当前 `_looks_like_missing_info` 可暂时保留，但不允许无限扩关键词解决联调。

执行规则：
1. 保留现有行为；
2. 增加真实Leave input-required integration test；
3. 如果稳定，保持；
4. 如果真实链错误completed，先查现有Leave/Runner是否已有结构化need-more-information authority；
5. 有则接结构化authority；
6. 没有且真实E2E不稳定 → 明确BLOCKER，不加测试专用强制分支。

禁止：
```text
if input == "我想请假": force input-required
```

## 12. cancel=false

这是必须修的Provider矛盾。

当前 Executor `cancel()` 不得再 `TaskUpdater.cancel()`。

正式：
```text
tasks/cancel
→ a2a-sdk 0.3.7 官方 unsupported-operation response
```

精确异常类型按当前固定SDK正式API实现，不自造200 JSON。

## 13. Result Artifact

继续：
```text
TextPart = result.answer
DataPart = result.to_payload()
```

status与A2A Task status一致。

禁止DataPart failed但Task completed，除Public Contract明确的业务not_found等合法completed语义。

## 14. Remote Router failure

内部remote capability异常可按现有策略fallback local。

但auth/contract parse错误不得fallback local。

## 15. Tests

覆盖：
- valid/invalid datetime；
- valid/invalid timezone；
- locale；
- attachment strict schema；
- unknown context拒绝；
- summary与正文隔离；
- Start/Resume same task/context；
- Resume subject变化按本次subject处理；
- input-required真实Task状态；
- terminal清理continuation；
- cancel unsupported；
- structured result状态一致；
- explicit failed → A2A failed。

## 16. DoD

Provider从Card、Public Request到Task状态与正式contract完全自洽：

```text
streaming=true
input_required=true
resume=true
cancel=false
durable=false
```
