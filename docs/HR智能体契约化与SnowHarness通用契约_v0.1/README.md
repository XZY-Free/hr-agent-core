# HR 智能体契约化与 SnowHarness 通用智能体契约 v0.1

本目录包含本阶段三份正式工作文档：

1. `00-HR智能体契约事实基线.md`
   - 只记录当前 `hr-agent-core` 真实代码事实；
   - 不把目标设计写成现状。

2. `01-HR智能体契约化改造方案.md`
   - 只针对 `hr-agent-core`；
   - 目标是把整个 HR Agent 暴露成一个 SnowHarness 可黑盒调用的顶层 Agent。

3. `02-SnowHarness通用智能体契约规范-v0.1-草案.md`
   - 从 HR Agent 抽象出的通用规则；
   - 当前仍是草案；
   - 必须经过 HR Agent 真改造和 SnowHarness 真联调后才能升级为正式规范。

## 当前不要直接生成通用 Skill

正确顺序：

```text
事实基线
→ HR Agent改造方案
→ 通用契约规范v0.1草案
→ Codex实施HR Agent
→ SnowHarness黑盒真联调
→ 修正规范
→ 第二个不同Agent验证
→ 规范v1.0
→ 通用Codex Skill
```

这样避免把尚未经过真实工程验证的猜测固化进Skill。
