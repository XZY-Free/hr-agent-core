"""AgentKit Knowledge 真实检索后端：基于 veADK KnowledgeBase(backend='viking')。

collection 名从环境变量读，按 scope 定向检索：
  policy / handbook / salary / childcare 各对应一个 Viking 知识库 collection；
  all = policy + handbook + salary 合并（与 local_stub 行为一致，不含 childcare）。

鉴权用火山引擎 AK/SK（VOLCENGINE_ACCESS_KEY / VOLCENGINE_SECRET_KEY），
由 veADK 的 VikingDBKnowledgeBackend 内部 SignerV4 签名。
- 本地未配 AK/SK 时，首次检索会抛鉴权错误。
- 部署到 AgentKit Runtime 后，可由平台 IAM 自动注入凭证（见 _set_service_info）。

参考：agentkit-samples/python/01-tutorials/06-agentkit-knowledge/viking_knowledge
      volcengine.github.io/agentkit-sdk-python/content/7.knowledge/1.knowledge_quickstart
"""
import os
import time

# scope → 要检索的 collection 键列表（all 聚合三库，与 local_stub._SCOPE_FILES 一致）
_SCOPE_COLLECTIONS: dict[str, list[str]] = {
    "policy": ["policy"],
    "handbook": ["handbook"],
    "salary": ["salary"],
    "childcare": ["childcare"],
    "all": ["policy", "handbook", "salary"],
}

# 模块级 KB 实例缓存：避免每次检索都触发 collection 存在性检查与鉴权握手
_KB_CACHE: dict[str, object] = {}


def _get_kb(collection: str):
    """懒加载 VikingDB KnowledgeBase 实例。

    首次调用触发 VikingDB 鉴权与 collection 存在性检查（需 AK/SK）。
    测试中通过 monkeypatch 本函数绕过网络。
    """
    from veadk.knowledgebase import KnowledgeBase

    if collection not in _KB_CACHE:
        _KB_CACHE[collection] = KnowledgeBase(backend="viking", index=collection)
    return _KB_CACHE[collection]


def _search_raw(kb, collection: str, query: str, top_k: int) -> list[dict]:
    """绕过 veADK 的 search() 封装，直接调底层 VikingKnowledgeBaseService.search_knowledge()。

    原因：veADK 的 KnowledgeBase.search() 把原始响应里的 score 和 doc_info.doc_name 丢了，
    只留 content。咨询 Agent 回答需要"引用哪份制度文档"，故取原始 result_list 自行解析。

    复用 veADK 已构造好的 _backend._viking_sdk_client（含 AK/SK 鉴权、host 解析），
    不自己拼签名。client 在 _search_knowledge 内部第一次成功调用前赋值（619 行），
    故先跑一次真实查询触发其构造，再直接用 client 拿原始响应。
    """
    backend = kb._backend
    if backend._viking_sdk_client is None:
        # 用真实 query 触发 client 构造（空 query 会被 VikingDB 参数校验拒绝）
        backend._search_knowledge(query=query, top_k=top_k)
    client = backend._viking_sdk_client

    # VikingDB 免费档有 QPS 限制，瞬时限流时等 1.2s 重试一次
    for attempt in range(2):
        try:
            response = client.search_knowledge(
                collection_name=collection,
                project=backend.volcengine_project,
                query=query,
                limit=top_k,
                post_processing={"rerank_swich": True, "chunk_diffusion_count": 0},
            )
            break
        except Exception as e:
            if attempt == 0 and "QPS" in str(e):
                time.sleep(1.2)
                continue
            raise

    results = []
    for r in response.get("result_list", []) or []:
        doc_info = r.get("doc_info", {}) or {}
        results.append({
            "content": r.get("content", "") or "",
            "source": doc_info.get("doc_name") or collection,
            "score": float(r.get("score", 0.0) or 0.0),
        })
    return results


class AgentKitKnowledgeBackend:
    """AgentKit 知识库检索后端（veADK VikingDB）。

    collection_map 可显式传入（测试用），否则从环境变量
    KB_COLLECTION_POLICY/HANDBOOK/SALARY/CHILDCARE 读取，缺省回退到 scope 名本身。
    """

    def __init__(self, collection_map: dict[str, str] | None = None):
        if collection_map is None:
            collection_map = {
                "policy": os.getenv("KB_COLLECTION_POLICY", "policy"),
                "handbook": os.getenv("KB_COLLECTION_HANDBOOK", "handbook"),
                "salary": os.getenv("KB_COLLECTION_SALARY", "salary"),
                "childcare": os.getenv("KB_COLLECTION_CHILDCARE", "childcare"),
            }
        self.collection_map = collection_map

    def search(self, query: str, scope: str, top_k: int = 5) -> list[dict]:
        """按 scope 检索知识库，返回 [{"content", "source", "score"}]。

        单库失败不阻断其他库（all 模式下个别库不可用仍返回其余结果）；
        整体失败由上层 kb_search 工具兜底为 kb_unavailable。
        """
        if scope not in _SCOPE_COLLECTIONS:
            return []

        results: list[dict] = []
        for key in _SCOPE_COLLECTIONS[scope]:
            collection = self.collection_map.get(key, key)
            try:
                kb = _get_kb(collection)
                results.extend(_search_raw(kb, collection, query, top_k))
            except Exception:
                continue
        return results
