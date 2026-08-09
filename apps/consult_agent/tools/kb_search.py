"""知识库检索工具：按 scope 查询并返回结构化结果。"""

from packages.hr_domain.schemas.tool_result import ok, err
from apps.consult_agent.knowledge.backend import KnowledgeBackendError, get_backend

_VALID_SCOPES = {"policy", "handbook", "salary", "childcare", "all"}


def kb_search(query: str, scope: str, tool_context) -> dict:
    """检索知识库。

    Args:
        query: 查询文本
        scope: 检索范围（policy / handbook / salary / childcare / all）
        tool_context: ADK 工具上下文
    """
    if scope not in _VALID_SCOPES:
        return err("invalid_scope", f"无效的 scope：{scope}，可选值为 {_VALID_SCOPES}")

    try:
        backend = get_backend()
        results = backend.search(query, scope=scope, top_k=5)
    except KnowledgeBackendError as exc:
        return err(exc.error_type, "知识库暂不可用，请稍后再试或转人工")
    except Exception:
        return err("kb_unavailable", "知识库暂不可用，请稍后再试或转人工")

    response = ok(list(results))
    failed_scopes = list(getattr(results, "failed_scopes", ()))
    if failed_scopes:
        response["partial_failure"] = True
        response["failed_scopes"] = failed_scopes
    return response
