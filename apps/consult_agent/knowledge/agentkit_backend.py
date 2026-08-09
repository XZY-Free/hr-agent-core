"""AgentKit/Viking 知识库适配层：使用 Viking 官方公开 SDK。

collection 名从环境变量读，按 scope 定向检索：
  policy / handbook / salary / childcare 各对应一个 Viking 知识库 collection；
  all = policy + handbook + salary 合并（与 local_stub 行为一致，不含 childcare）。

鉴权由官方 SDK 使用服务端环境中的 AK/SK/STS token 完成。本模块不访问 veADK
私有成员、不实现签名，也不把查询正文、切片正文或凭据写入 Trace。
"""
import os
import time
from functools import lru_cache
from numbers import Real
from typing import Callable

import requests
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from volcengine.viking_knowledgebase import VikingKnowledgeBaseService

from apps.consult_agent.knowledge.types import KnowledgeBackendError, KnowledgeSearchResults

# scope → 要检索的 collection 键列表（all 聚合三库，与 local_stub._SCOPE_FILES 一致）
_SCOPE_COLLECTIONS: dict[str, list[str]] = {
    "policy": ["policy"],
    "handbook": ["handbook"],
    "salary": ["salary"],
    "childcare": ["childcare"],
    "all": ["policy", "handbook", "salary"],
}

_COLLECTION_ENV = {
    "policy": "KB_COLLECTION_POLICY",
    "handbook": "KB_COLLECTION_HANDBOOK",
    "salary": "KB_COLLECTION_SALARY",
    "childcare": "KB_COLLECTION_CHILDCARE",
}


def _required_env(name: str, error_type: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise KnowledgeBackendError(error_type)
    return value


def _collections_from_env() -> dict[str, str]:
    return {
        scope: _required_env(env_name, "knowledge_configuration_error")
        for scope, env_name in _COLLECTION_ENV.items()
    }


@lru_cache(maxsize=1)
def _official_viking_client() -> VikingKnowledgeBaseService:
    kwargs = {
        "ak": _required_env(
            "VOLCENGINE_ACCESS_KEY", "knowledge_authentication_failed"
        ),
        "sk": _required_env(
            "VOLCENGINE_SECRET_KEY", "knowledge_authentication_failed"
        ),
    }
    optional_env = {
        "host": "VIKING_KNOWLEDGE_HOST",
        "region": "VIKING_KNOWLEDGE_REGION",
        "scheme": "VIKING_KNOWLEDGE_SCHEME",
        "sts_token": "VOLCENGINE_SESSION_TOKEN",
    }
    for argument, env_name in optional_env.items():
        value = os.getenv(env_name, "").strip()
        if value:
            kwargs[argument] = value
    try:
        return VikingKnowledgeBaseService(**kwargs)
    except Exception as exc:
        raise _safe_error(exc) from None


def _is_qps_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "qps" in text or "rate limit" in text or "too many requests" in text


def _safe_error(exc: Exception) -> KnowledgeBackendError:
    if isinstance(exc, (ConnectionError, TimeoutError, requests.RequestException)):
        return KnowledgeBackendError("knowledge_network_error")
    text = str(exc).lower()
    if any(marker in text for marker in (
        "signature", "unauthorized", "forbidden", "access denied",
        "accessdenied", "invalidaccess", "credential",
    )):
        return KnowledgeBackendError("knowledge_authentication_failed")
    if _is_qps_error(exc):
        return KnowledgeBackendError("knowledge_rate_limited")
    return KnowledgeBackendError("knowledge_service_error")


def _map_response(response) -> list[dict]:
    if not isinstance(response, dict) or "result_list" not in response:
        raise KnowledgeBackendError("knowledge_invalid_response")
    rows = response["result_list"]
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise KnowledgeBackendError("knowledge_invalid_response")

    results = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("content"), str)
            or "score" not in row
            or not isinstance(row.get("doc_info"), dict)
        ):
            raise KnowledgeBackendError("knowledge_invalid_response")
        source = row["doc_info"].get("doc_name")
        if not isinstance(source, str) or not source.strip():
            raise KnowledgeBackendError("knowledge_source_missing")
        score = row["score"]
        if isinstance(score, bool) or not isinstance(score, Real):
            raise KnowledgeBackendError("knowledge_invalid_response")
        results.append({
            "content": row["content"],
            "source": source,
            "score": float(score),
        })
    return results


class AgentKitKnowledgeBackend:
    """AgentKit/Viking 资源的官方 SDK 检索适配层。

    collection_map 和 client 可显式注入用于单元测试；生产环境从服务端环境变量
    读取 collection 和凭据。
    """

    def __init__(
        self,
        collection_map: dict[str, str] | None = None,
        *,
        client=None,
        project: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        tracer=None,
    ):
        self.collection_map = collection_map or _collections_from_env()
        if any(not self.collection_map.get(scope) for scope in _COLLECTION_ENV):
            raise KnowledgeBackendError("knowledge_configuration_error")
        self.client = client or _official_viking_client()
        self.project = project or os.getenv("VIKING_KNOWLEDGE_PROJECT") or None
        self.sleep = sleep
        self.tracer = tracer or trace.get_tracer(__name__)

    def _search_collection(
        self, collection: str, query: str, top_k: int
    ) -> list[dict]:
        kwargs = {
            "collection_name": collection,
            "query": query,
            "limit": top_k,
            "post_processing": {
                "rerank_swich": True,
                "chunk_diffusion_count": 0,
            },
        }
        if self.project:
            kwargs["project"] = self.project

        for attempt in range(2):
            try:
                return _map_response(self.client.search_knowledge(**kwargs))
            except KnowledgeBackendError:
                raise
            except Exception as exc:
                if attempt == 0 and _is_qps_error(exc):
                    self.sleep(1.2)
                    continue
                raise _safe_error(exc) from None
        raise KnowledgeBackendError("knowledge_rate_limited")

    def search(
        self, query: str, scope: str, top_k: int = 5
    ) -> KnowledgeSearchResults:
        """按 scope 检索知识库，返回 [{"content", "source", "score"}]。

        单库失败不阻断其他库（all 模式下个别库不可用仍返回其余结果）；
        整体失败由上层 kb_search 工具兜底为 kb_unavailable。
        """
        if scope not in _SCOPE_COLLECTIONS:
            raise KnowledgeBackendError("knowledge_invalid_scope")

        scope_keys = _SCOPE_COLLECTIONS[scope]
        collections = [self.collection_map[key] for key in scope_keys]
        started = time.perf_counter()
        with self.tracer.start_as_current_span(
            "knowledge.search",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("knowledge.scope", scope)
            span.set_attribute("knowledge.collection", ",".join(collections))
            span.set_attribute("knowledge.top_k", top_k)
            results: list[dict] = []
            failures: list[tuple[str, KnowledgeBackendError]] = []
            for scope_key, collection in zip(scope_keys, collections, strict=True):
                try:
                    results.extend(self._search_collection(collection, query, top_k))
                except KnowledgeBackendError as exc:
                    failures.append((scope_key, exc))

            if failures and (scope != "all" or len(failures) == len(scope_keys)):
                error = failures[0][1]
                span.set_attribute("knowledge.result_count", 0)
                span.set_attribute("knowledge.partial_failure", False)
                span.set_attribute("knowledge.error_type", error.error_type)
                span.set_attribute(
                    "knowledge.elapsed_ms", (time.perf_counter() - started) * 1000
                )
                span.set_status(Status(StatusCode.ERROR))
                raise error

            failed_scopes = tuple(key for key, _ in failures)
            span.set_attribute("knowledge.result_count", len(results))
            span.set_attribute("knowledge.partial_failure", bool(failed_scopes))
            span.set_attribute(
                "knowledge.error_type",
                failures[0][1].error_type if failures else "none",
            )
            span.set_attribute(
                "knowledge.elapsed_ms", (time.perf_counter() - started) * 1000
            )
            return KnowledgeSearchResults(results, failed_scopes=failed_scopes)
