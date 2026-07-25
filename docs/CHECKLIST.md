# 外部依赖核验清单（用户提供材料后按序执行）

## A. 模型 Key（最先做）
1. `.env` 写入方舟 Key（veADK 配置项见 config.yaml / 官方文档）与 `MODEL_AGENT_NAME`
2. `uv run pytest -m eval -v` → 22 条评测逐条过；失败的迭代 prompts.py 措辞
3. 通过标准：22/22 pass

## B. 知识库（拿到 AgentKit 库 ID 后）
1. 确认 4 个库已在 AgentKit 建好（制度/操作手册/薪酬福利/地区育儿假），职级对照表已随薪酬库导入
2. `.env`: `KB_BACKEND=agentkit` + `KB_COLLECTION_POLICY/HANDBOOK/SALARY/CHILDCARE=<库ID>`
3. 实现 `AgentKitKnowledgeBackend.search()`（veADK KnowledgeBase / AgentKit Knowledge API，核验时定）
4. 重跑评测 A.2；对比 stub 期答案质量，检索差的在 AgentKit 控制台调分段/参数

## C. 请假提交接口（拿到接口文档后）
1. 实现 `hr_agent/tools/gaia/submit.py::_do_submit`（映射 LeaveForm payload → 真实接口）
2. 新增 mock 单测；沙箱环境真调一次
3. `.env`: `GAIA_DRY_RUN=false` 灰度开启

## D. 部署（拿到火山账号后）
按 deploy/README.md：本地 client 验证 state 传参与 [[JUMP]] 透传 → agentkit deploy → 线上重验
