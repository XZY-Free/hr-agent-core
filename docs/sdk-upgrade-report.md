# SDK 升级与 Knowledge 适配报告

状态：批次 1 完成

检查时间：2026-08-09（Asia/Shanghai）

## 1. 结论

本批只替换 Knowledge 检索适配层并升级冻结依赖，没有改变知识库产品、四个 scope、collection 映射、`top_k=5`、知识文档、咨询 Agent 提示词或 21 条评测业务期望。

Knowledge 已从 veADK 私有成员迁移到 Viking 官方公开 SDK：

```text
hr-agent
→ KnowledgeBackend
→ AgentKit / Viking Knowledge 资源
→ volcengine.viking_knowledgebase.VikingKnowledgeBaseService.search_knowledge
```

真实响应稳定提供 `result_list[].content`、`result_list[].doc_info.doc_name` 和 `result_list[].score`。适配层分别原样映射为 `content/source/score`；文档名缺失或响应结构异常时明确失败，不使用 collection 名、固定值或重算值兜底。

## 2. 依赖结果

| 包 | 批次 0 | 批次 1 | 说明 |
|---|---:|---:|---|
| `agentkit-sdk-python` | 0.5.10 | 0.8.1 | 冻结目标版本 |
| `veadk-python` | 0.5.37 | 1.1.0 | 冻结目标版本 |
| `google-adk` | 1.32.0 | 2.2.0 | 两个目标包共同支持的正式版本 |
| `volcengine` | 1.0.226 | 1.0.226 | 已锁定正式版本；Knowledge 公开客户端来自该发行包 |
| `volcengine-python-sdk` | 5.0.42 | 5.0.42 | 按要求复用当前锁定正式版本，未升级 |

依赖由 `uv lock` 正常解析；未使用预发布版本、降级、`--no-deps` 或强制忽略冲突。

## 3. 公开 SDK 调用与字段映射

公开调用：

```python
VikingKnowledgeBaseService.search_knowledge(
    collection_name=collection,
    query=query,
    limit=top_k,
    project=project,
    post_processing={
        "rerank_swich": True,
        "chunk_diffusion_count": 0,
    },
)
```

响应映射：

| 公开响应字段 | 对外字段 | 处理 |
|---|---|---|
| `result_list[].content` | `content` | 原始切片正文，不写入日志或 Trace |
| `result_list[].doc_info.doc_name` | `source` | 原始文档名；缺失时返回 `knowledge_source_missing` |
| `result_list[].score` | `score` | 原始数值，仅做 Python `float` 类型承载；`0` 不丢弃 |

生产代码不再访问 `kb._backend`、`backend._viking_sdk_client`、`backend._search_knowledge()` 或其他 SDK 私有成员，也没有复制 veADK 内部实现或自行实现签名算法。

## 4. scope 与失败语义

| scope | collection 环境变量 | 行为 |
|---|---|---|
| `policy` | `KB_COLLECTION_POLICY` | 单库检索 |
| `handbook` | `KB_COLLECTION_HANDBOOK` | 单库检索 |
| `salary` | `KB_COLLECTION_SALARY` | 单库检索 |
| `childcare` | `KB_COLLECTION_CHILDCARE` | 单库检索 |
| `all` | policy + handbook + salary | 聚合三库，明确不含 childcare |

- 所有 scope 继续使用 `top_k=5`。
- QPS 限流沿用等待 1.2 秒后重试一次的语义。
- 指定单库失败会返回明确错误；检索成功但无结果返回空列表，两者可区分。
- `all` 单库失败时保留其他成功库结果，并返回 `partial_failure=true` 与 `failed_scopes`；三库全部失败时返回明确错误。

## 5. 鉴权和配置

本地开发：

- `VOLCENGINE_ACCESS_KEY`、`VOLCENGINE_SECRET_KEY` 从本地 `.env` 注入；临时凭据再注入 `VOLCENGINE_SESSION_TOKEN`。
- 四个 collection、host、region、scheme、project 均由环境变量配置；应用代码不硬编码。
- `.env`、真实 `agentkit.yaml`、SDK 原始异常和认证信息不进入 Git、日志、Trace 或测试快照。

AgentKit Runtime：

- 在 Runtime 服务端环境变量中配置四个 collection 和 Viking endpoint 参数。
- 长期 AK/SK 只能作为 Runtime secret 注入；采用 IAM/STS 时同时注入三段临时凭据并定期轮换。
- 批次 6 前不创建、不更新 Runtime；Runtime IAM/STS 的实际关联方式仍需在云端部署门禁后验证。

详细变量清单见 `.env.example` 和 `deployment/README.md`。

## 6. 可观测性差异

官方 SDK 调用增加 `knowledge.search` OpenTelemetry span，仅记录：

```text
knowledge.scope
knowledge.collection
knowledge.top_k
knowledge.result_count
knowledge.partial_failure
knowledge.error_type
knowledge.elapsed_ms
```

单元测试已验证上述字段，同时验证 span 不包含查询正文、切片正文、AK/SK、JWT、签名或认证头。

评测证据中的 `kb_search` 工具响应只保留 `result_count/source/score` 和失败标记，不落盘 `content`；测试与 Runtime 配置使用 `LOGGING_LEVEL=INFO` 或更高等级，避免 veADK DEBUG 日志输出完整工具响应。

平台差异：

| 项 | 当前结论 |
|---|---|
| Trace 是否能看到 Knowledge 调用 | 代码和内存 exporter 已验证自定义 `knowledge.search` span；当前本地未启用远端 exporter，平台 Trace 展示未验证 |
| AgentKit“知识库分析”是否仍能关联 | 官方 SDK 直调不再经过 veADK Knowledge 封装，平台自动关联未验证 |
| 缺失的平台能力 | 可能缺少 veADK 专用 Knowledge 调用分类、资源面板自动关联和检索详情页 |
| 补充方式 | 保留标准 OpenTelemetry span，批次 6 在开发 Runtime 验证 exporter 与平台关联；不退回私有成员 |

升级后 SSE 事件新增公开字段 `nodeInfo`，其余会话、SSE 和 `JUMP` 行为保持通过。

## 7. 真实 Viking 回归证据

真实回归使用四个现有 collection，未更换知识库、未修改文档。测试只输出文档名、原始 score、切片长度，不输出切片正文。

| scope | 返回数 | 首条 source | 首条原始 score |
|---|---:|---|---:|
| policy | 5 | `华润啤酒考勤休假管理制度-华啤 A03-24-人力 26C.docx` | 0.2724906802177429 |
| handbook | 5 | `考勤管理系统操作手册-0721.docx` | 0.3463975191116333 |
| salary | 5 | `收入证明等薪酬业务FAQ.csv` | 0.2675437927246094 |
| childcare | 5 | `各省市地方假期政策20260629.xlsx` | 0.35281240940093994 |

已知低质量问题仍可观察：查询“火星基地宠物报销制度”在 policy 库仍返回 5 条，首两条原始 score 为 0.19036859273910522 和 0.1682356595993042。适配层没有新增阈值，因此低质量召回没有被隐藏，仍可由 `source/score` 诊断。

## 8. 测试结果

| 验证 | 结果 | 证据 |
|---|---|---|
| Knowledge 特征与错误测试 | 24 passed | `tests/unit/test_knowledge_backend.py` |
| 评测分类与日志脱敏测试 | 4 passed | `tests/unit/test_eval_log_redaction.py` |
| 全部非评测测试（最终门禁） | 110 passed，5 skipped，21 deselected | 本批本地测试输出 |
| 真实 Viking Knowledge | 5 passed | `tests/integration/test_viking_knowledge.py` |
| 21 条真实模型核心业务评测 | 21 passed，115 deselected | `tests/eval/logs/eval-20260809-160442.log` |
| 本地健康检查 | `{"status":"ok"}` | 本批本地 HTTP 验证输出 |
| 会话创建 | HTTP 200 | session `batch1-closeout-20260809` |
| SSE | 3 events，0 error events | 本批本地 HTTP 验证输出 |
| `JUMP` 标记 | `[[JUMP:punch-details]]` 完整保留 | 本批本地 HTTP 验证输出 |

21 条评测使用真实方舟模型和真实 Viking Knowledge；盖亚调用和文档下载仍按既有评测边界使用 stub，不冒充真实盖亚验证。

### 8.1 核心业务门禁与非阻塞质量指标

原21条用例全部保留。`followup_present`的核心业务门禁为：必须调用`kb_search`、必须答出年假可跨年度、必须包含次年3月31日这一截止事实。推荐追问“还想了解”单独记录为`recommended_followup`质量指标，不参与Pytest失败判定。

固定独立运行5次，不追加运行次数：

| 次数 | 核心业务 | 推荐追问 | 证据 |
|---:|---|---|---|
| 1 | 通过 | 命中 | `tests/eval/logs/eval-20260809-160300.log` |
| 2 | 通过 | 命中 | `tests/eval/logs/eval-20260809-160311.log` |
| 3 | 通过 | 未命中 | `tests/eval/logs/eval-20260809-160322.log` |
| 4 | 通过 | 命中 | `tests/eval/logs/eval-20260809-160331.log` |
| 5 | 通过 | 命中 | `tests/eval/logs/eval-20260809-160342.log` |

固定样本命中4次，命中率80%。未命中样本仍调用`transfer_to_agent`和`kb_search`，答复“年休假可延期至次年3月31日、只可跨年度结转一次”，没有业务幻觉、工具错路由、来源丢失或数字编造。完整21条门禁中的额外一次观察也未命中，但核心业务仍通过；该次不计入固定5次命中率。

该指标只反映生成话术是否追加自然推荐，不是SDK升级导致的业务能力退化。本批不修改咨询提示词、模型、thinking、temperature或其他生成参数，也不硬编码固定追问；避免把依赖与Knowledge技术债清理扩展成措辞调参。

## 9. 尚待批次 6 验证

- 开发 Runtime 的 IAM/STS 关联和临时凭据轮换。
- 开发 Runtime 的远端 Trace exporter 是否展示 `knowledge.search`。
- AgentKit“知识库分析”是否能自动关联官方 SDK 直调。
- 多实例、Runtime 重启和真实 A2A 场景不属于批次 1，将按冻结批次执行。
