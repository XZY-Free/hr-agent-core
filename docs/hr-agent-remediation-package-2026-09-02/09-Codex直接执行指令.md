# 给 Codex / 编码 AI 的直接执行指令

把下面整段作为编码 AI 的首条任务指令使用。

---

你现在位于 `hr-agent-core` 项目根目录。

你的任务不是重新审查项目，也不是重新设计方案。

你必须严格实施工程包：

`hr-agent-remediation-package-2026-09-02`

## 一、先读什么

先完整阅读：

1. `00-README-执行总控.md`
2. `08-实施顺序与文件变更矩阵.md`
3. 当前正在实施的 WP 文档

不要先扫描项目后自行提出另一套方案。

工程包已经完成业务审查与架构决策，你的职责是实施。

---

## 二、工作边界

只允许修改当前 `hr-agent-core` 项目。

禁止：

- 修改 SnowHarness；
- 修改其他本地仓库；
- push 到远端；
- 创建与工程包无关的新架构；
- 重做一次 FastGPT 审计；
- 重新讨论是否需要这些整改；
- 用“我认为更简单”删除业务规则；
- 把旧 FastGPT 工作流节点结构照搬回来。

---

## 三、本轮明确不处理

以下是假实现问题，当前工程包明确排除：

- page_jump 对后端业务 JSON 的真实输出；
- handoff 的真实转接动作；
- leave_support 最终业务 JSON / dry-run 对外契约；
- 撤回、销假等真实业务动作契约；
- 其他“Agent 说已执行但后端没有真实动作”的整改。

不要顺手实现。

如果修改公共文件时遇到相关代码，保持当前对外语义不变。

---

## 四、实施顺序

严格：

1. WP-01 身份与 Gaia
2. WP-02 Leave Draft 与规则
3. WP-03 Employee Data
4. WP-04 Attendance
5. WP-05 Semantic Routing / continuation
6. WP-06 Attachments
7. WP-07 Production Topology Acceptance

不得跨包同时大改。

---

## 五、每个 WP 的实施方式

对每个 WP：

1. 阅读文档中的“当前问题”；
2. 阅读“目标架构/固定规则”；
3. 按“文件范围”修改；
4. 按“测试矩阵”新增/修改测试；
5. 执行测试；
6. 执行全量相关回归；
7. 输出完成报告。

不要先输出一个新的实施方案等用户确认。

---

## 六、禁止自由发挥

文档里出现：

- 必须
- 不得
- 固定
- Authority
- fail closed
- completion gate

都视为强约束。

没有业务规则证据时：

- 不猜；
- 不补默认值；
- 不新增业务口径；
- 不静默 fallback。

例如：

- 未知排班不能当工作日；
- 未知单位不能按天；
- 缺理由不能写“个人事务”；
- employee identity 未解析不能用 user_id；
- 10分钟内迟到缺月度豁免上下文不能假定第一次。

---

## 七、不要为了兼容保留双轨

项目仍处开发整改阶段。

如果新 Authority 已经接管生产路径：

- 删除旧生产 Authority；
- 不保留两套 identity；
- 不保留两套 leave duration；
- 不保留 regex business routing + semantic routing 双重决策。

只有测试 fixture / 明确 legacy eval 可以保留隔离的旧适配。

---

## 八、测试要求

禁止：

- skip 新失败 case；
- xfail 掩盖问题；
- 把 expected 改成当前错误行为；
- 只跑自己新增的 3 个测试就宣布完成；
- 使用 monolithic local_agent 证明 production topology。

每个 WP 都必须运行：

- 本 WP tests；
- 相关 integration；
- 全量 unit；
- `git diff --check`。

最终 WP-07 必须跑 production-topology suite。

---

## 九、状态报告格式

每个 WP 只输出：

### 修改文件

逐项列出。

### 完成要求

对文档门禁逐项：

- PASS
- FAIL
- BLOCKED

### 测试

写：

- 命令
- passed
- failed
- skipped

### 未完成

如果没有：

`无`

如果有：

明确列出，不能写“整体已完成”。

---

## 十、遇到阻塞

如果某个外部能力确实不存在，例如附件 resolver 没有外部实现：

按工程包要求做 fail-closed 边界和明确错误。

不要：

- 编造外部 API；
- 修改 SnowHarness；
- 假装已完成外部集成。

---

## 十一、完成一个 WP 后

不要重新审查剩余项目，也不要生成“下一阶段新方案”。

直接进入工程包下一个 WP。

如果实际代码与基线 commit 已经发生变化：

- 只判断变化是否已经满足当前文档明确要求；
- 满足则复用；
- 不满足则按文档收敛；
- 不以“代码已变化”为理由重新设计。

---

现在直接从 WP-01 开始实施。
