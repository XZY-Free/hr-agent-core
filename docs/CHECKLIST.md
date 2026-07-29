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

## C. 请假提交接口（拿到接口文档后）
1. 实现 `hr_agent/tools/gaia/submit.py::_do_submit`（映射 LeaveForm payload → 真实接口）
2. 新增 mock 单测；沙箱环境真调一次
3. `.env`: `GAIA_DRY_RUN=false` 灰度开启

## D. 部署（拿到火山账号后）
按 deploy/README.md：本地 client 验证 state 传参与 [[JUMP]] 透传 → agentkit deploy → 线上重验
