# 外部依赖核验清单（用户提供材料后按序执行）

## A. 模型 Key（最先做）
1. `.env` 写入方舟 Key（veADK 配置项见 config.yaml / 官方文档）与 `MODEL_AGENT_NAME`
2. `uv run pytest -m eval -v` → 22 条评测逐条过；失败的迭代 prompts.py 措辞
3. 通过标准：22/22 pass

> **进展**：方舟 Key 已配 `.env`，22 条评测已跑通（**20/22 稳定通过**，剩余 2 条为模型随机性的同义表达/行为波动，已用 `expect_any_keyword`/放宽断言容纳）。首轮暴露并修复 6 个 bug（详见 architecture-overview §九）：conftest 未加载 .env、评测脚本未建 session、未过滤 thinking part、跳转回调 `state.pop` 在 ADK State 上 AttributeError、今天日期未注入 prompt、stub 排班未按日期范围过滤。另有 kb_search 单测依赖全局后端配置，已改显式挂桩。

## B. 知识库（拿到火山 AK/SK + 确认库名后）
> 真检索代码已实现（`hr_agent/knowledge/agentkit_backend.py`，82 单测含 3 条覆盖），只差凭证与库名。

1. 确认 4 个库已在 AgentKit 建好（制度/操作手册/薪酬福利/地区育儿假），职级对照表已随薪酬库导入
2. 确认 4 个库的 **collection 名**（控制台知识库详情页；若建库时直接用了 `policy`/`handbook`/`salary`/`childcare`，则代码缺省值已匹配，无需配 `KB_COLLECTION_*`）
3. `.env`：`KB_BACKEND=agentkit` + `VOLCENGINE_ACCESS_KEY` / `VOLCENGINE_SECRET_KEY`（火山引擎 AK/SK，获取：console.volcengine.com/iam/keymanager）
4. 连通性冒烟：`uv run python -c "from hr_agent.knowledge.agentkit_backend import AgentKitKnowledgeBackend as B; print(B().search('迟到扣款','policy',3))"` 应返回真库内容
5. 重跑评测 A.2；对比 stub 期答案质量，检索差的在 AgentKit 控制台调分段/参数

### B.6 已知的内容缺口与检索质量问题（2026-07-30 逐条审执行轨迹后发现）

评测断言全绿也不代表答得对——以下问题是通读 `tests/eval/logs/` 的执行轨迹
发现的，断言层面完全没暴露：

| 问题 | 现象 | 处理 |
|---|---|---|
| **病假工资制度缺失** | "公司的病假工资制度是怎么规定的" → 三种问法 top score 均 ≤0.29，召回的是医疗期天数表与病假条审批规则，没有一条讲病假期间工资怎么发。模型诚实拒答（行为正确），但这是业务高频问题 | 需业务确认原文档是否有此章节；有则补充导入。补齐后可把评测 case `policy_probation` 换回病假工资 |
| **加班调休检索错配** | 查"加班调休规定" → 召回**育儿假**内容（top score 0.279） | 控制台调分段：该制度文档的分段可能把章节标题与内容切散了 |
| **婚假答偏** | 查"婚假天数规定" → 召回"婚假是否需一次性休完"的 FAQ，答不到天数 | 同上；确认婚假天数是否在库内 |
| **top1 常不相关** | `salary_term_alias` 查"膳食福利标准"top1 是高原津贴/商业保险；`followup_present` 查"年假跨年"top1 是离职年假 FAQ。模型能从后续结果里筛出正确内容，但召回精度不高（多数 score 0.2~0.3） | 控制台调 rerank 与分段粒度；score 普遍偏低说明 embedding 匹配度有优化空间 |

> 已验证覆盖良好的主题（可作为回归基准）：迟到扣款分段计费（0.4+）、四川育儿假
> 10 天（0.43）、试用期转正流程（0.49）、餐补标准分档、年假跨年结转、医疗期天数表。

## C. 请假提交 —— ✅ 无需接口，当前已是正式形态

> **2026-07-25 业务确认**（见 `迁移梳理/接口适配清单.md` §8、迁移梳理报告 §9.3）：
> 调用链为「后端 → 智能体」，智能体**只输出请假单 JSON**，由后端拿到 JSON 后
> 自行调用盖亚请假接口提交，**智能体侧无提交动作**。
>
> 因此 `GAIA_DRY_RUN=true`（默认）返回的 `{"submitted": false, "form": payload}`
> 就是交付形态，不是待补的临时实现。此前把本项列为"待接口文档"是记录错误。

若将来改为智能体直连提交，`submit.py::_do_submit` 已有可运行的示例实现
（`GAIA_DRY_RUN=false` 启用，3 条 mock 单测覆盖成功/接口失败/网络异常），
拿到接口文档后需核对三处：

1. `GAIA_SUBMIT_PATH`（默认 `/atd-webapi/api/gaiaStandard/leave/submitLeaveApply/{corp_id}`，
   按盖亚同类接口形态占位）与 `GAIA_SUBMIT_ENV`（默认 `sandbox`）
2. payload 字段名——当前沿用 `LeaveForm.to_submit_payload()` 的旧系统
   leave_support 结构并补 `employeeId`
3. 成功判定——当前按 `result=true` 且 `code=200`，失败取 `message`

## D. 部署 —— ✅ 已上线（2026-07-30）
1. ~~本地 client 验证 state 传参与 [[JUMP]] 透传~~ ✅（顺带修了查询工具失败时假转人工的降级缺陷）
2. ~~agentkit config / launch~~ ✅ 已部署到 AgentKit Runtime，
   endpoint 与云资源清单见 deploy/README.md（**资源在计费，不用时 `agentkit destroy`**）
3. ~~线上重验~~ ✅ state 传参 / 查询降级 / JUMP 透传 / 真 Viking 库检索均通过
4. 后续：改代码后 `uv run agentkit launch` 重部署（endpoint 不变），详见 deploy/README.md

## E. 响应延迟 —— ✅ 已实测定论：关闭 thinking

### E.1 问题（2026-07-30 实测）

评测轨迹里的耗时（`tests/eval/logs/`，真模型 doubao-seed-1.6 + 真 Viking 库，
盖亚接口挂桩故不含其网络耗时）：

- **单轮延迟中位 26.8s，25 轮里 10 轮 >30s，最慢 62.9s**
- 一次完整请假（复述确认 + 提交两轮）**82s**
- 22 条 case 累计思考 **37697 字**

延迟随"模型往返跳数"线性增长：

| 路径 | 例子 | 耗时 |
|---|---|---|
| 纯固定话术（0 次工具） | handoff / cancel_leave | 4.5s / 7.2s |
| root_agent 直接调工具 | balance_query / personal_data_not_kb | 12.7s / 14.1s |
| transfer → 子 agent → 工具 | consult_transfer / policy_late_fine | 34.3s / 32.3s |
| transfer → 子 agent → 多工具 × 2 轮 | quick_tomorrow | 82.0s |

根因是 doubao-seed-1.6 的推理模式：每一跳（root 判断、transfer、子 agent 判断、
组织回答）都付一次完整 thinking 开销，单跳 400~1800 字。

### E.2 对照实验结论：全部关闭 thinking

`THINKING_DEFAULT=disabled`（见 `hr_agent/agents/model_config.py`，也可按 agent
用 `THINKING_ROOT/LEAVE/CONSULT` 单独覆盖）：

| 组 | thinking | 通过 | 全量耗时 |
|---|---|---|---|
| A 基准 | 全开 | 22/22 | 656.8s |
| B | 全关 | **22/22（连跑两轮）** | **138.9s / 139.8s** |

**耗时降 79%，通过率不变，稳定性更好**——开 thinking 时每轮全量都有 1~2 条不同
case 随机掉红，全关后连续两轮全绿。

回答质量不降，反而更详细（逐条对比轨迹得出，非仅看断言）：
- `salary_term_alias`：开 thinking 给出 550/700/600/500 四档标准；关 thinking
  额外给出计算公式、扣款天数定义、异地调动分段规则与莆田按厦门 A 档的特例
- `policy_late_fine`：规则一致，关 thinking 版本多带制度编号，旷工判定拆分更清楚
- `balance_query`：12.7s→5.4s，回答从"余额为4天"变成"总天数5天，已用1天，剩余4天"

推测原因：thinking 阶段已把内容"想过一遍"，最终输出倾向精简；关掉后模型直接把
检索结果组织成完整答案。原先担心的"consult_agent 需要推理筛低质量检索结果"
未成立——知识库咨询类 case 全部通过且答得更全。

> 附带收益：评测从 11 分钟降到 2.3 分钟，可以连跑多轮验稳定性，回归成本大幅下降。

### E.3 已落地与后续

- [x] **`disabled` 已设为代码默认值**（`model_config.py::DEFAULT_THINKING`，8 条单测
      覆盖）。部署时无需额外配置即为快档；需要推理时显式设 `THINKING_DEFAULT=enabled`，
      或用 `THINKING_<KEY>` 只给某个 agent 开回来
- [ ] 若仍嫌慢，下一步可试：把高频意图（余额/医疗期/页面跳转/固定话术）留在
      root_agent 不 transfer（实测这类已 4~14s），或换 doubao-seed-1.6-flash
      （`MODEL_AGENT_NAME_<KEY>` 可按 agent 换模型，22 条断言可直接当回归基准）。
      当前单轮已降到 5~15s 量级，此项收益递减，待线上叠加盖亚接口耗时后再评估
- [ ] 前端体感：流式输出 + "正在查询排班…"过程提示

> 注意：评测挂桩了盖亚接口，真实环境还要叠加 7 个 HTTP 接口的网络耗时（JWT
> 获取已有缓存，但排班/余额/权限查询是真实往返），线上延迟会高于上述数字。
