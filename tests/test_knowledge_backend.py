"""KnowledgeBackend 抽象层与本地桩测试。"""
import os

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from hr_agent.knowledge.local_stub import LocalStubBackend
from hr_agent.knowledge.backend import get_backend


def test_stub_search_hits_relevant_chunk():
    b = LocalStubBackend()
    r = b.search("迟到会扣多少钱", scope="policy", top_k=3)
    assert r and "五十元" in r[0]["content"]
    assert r[0]["source"] == "policy.md"


def test_stub_scope_isolation():
    b = LocalStubBackend()
    r = b.search("四川育儿假几天", scope="childcare", top_k=1)
    assert "十天" in r[0]["content"]
    assert all(x["source"] == "childcare.md" for x in r)


def test_scope_all_excludes_childcare():
    b = LocalStubBackend()
    r = b.search("育儿假", scope="all", top_k=10)
    assert all(x["source"] != "childcare.md" for x in r)


def test_factory_defaults_to_stub(monkeypatch):
    monkeypatch.delenv("KB_BACKEND", raising=False)
    assert isinstance(get_backend(), LocalStubBackend)


# ---------- AgentKit/Viking 官方 SDK 适配 ----------


class FakeVikingClient:
    def __init__(self, responses):
        self.responses = {
            collection: list(values) if isinstance(values, list) else values
            for collection, values in responses.items()
        }
        self.calls = []

    def search_knowledge(self, **kwargs):
        self.calls.append(kwargs)
        value = self.responses[kwargs["collection_name"]]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def _response(*rows):
    return {"rewrite_query": None, "result_list": list(rows)}


def _row(content="迟到扣款五十元", source="考勤制度.md", score=0.92):
    return {
        "content": content,
        "doc_info": {"doc_name": source},
        "score": score,
    }


def _backend(client, **kwargs):
    from hr_agent.knowledge.agentkit_backend import AgentKitKnowledgeBackend

    return AgentKitKnowledgeBackend(
        collection_map={
            "policy": "col-policy",
            "handbook": "col-handbook",
            "salary": "col-salary",
            "childcare": "col-childcare",
        },
        client=client,
        **kwargs,
    )


def test_factory_returns_agentkit_when_env_set(monkeypatch):
    from hr_agent.knowledge.agentkit_backend import AgentKitKnowledgeBackend

    monkeypatch.setenv("KB_BACKEND", "agentkit")
    monkeypatch.setenv("VOLCENGINE_ACCESS_KEY", "test-ak")
    monkeypatch.setenv("VOLCENGINE_SECRET_KEY", "test-sk")
    monkeypatch.setenv("KB_COLLECTION_POLICY", "col-policy")
    monkeypatch.setenv("KB_COLLECTION_HANDBOOK", "col-handbook")
    monkeypatch.setenv("KB_COLLECTION_SALARY", "col-salary")
    monkeypatch.setenv("KB_COLLECTION_CHILDCARE", "col-childcare")
    b = get_backend()
    assert isinstance(b, AgentKitKnowledgeBackend)


def test_official_sdk_single_collection_preserves_content_source_score():
    client = FakeVikingClient({"col-policy": _response(_row())})
    b = _backend(client)
    r = b.search("迟到扣款", scope="policy", top_k=5)

    assert r and r[0]["content"] == "迟到扣款五十元"
    assert r[0]["source"] == "考勤制度.md"
    assert r[0]["score"] == 0.92
    assert client.calls == [{
        "collection_name": "col-policy",
        "query": "迟到扣款",
        "limit": 5,
        "post_processing": {"rerank_swich": True, "chunk_diffusion_count": 0},
    }]


def test_official_sdk_preserves_zero_score():
    client = FakeVikingClient({"col-policy": _response(_row(score=0))})
    r = _backend(client).search("迟到扣款", scope="policy", top_k=5)

    assert r[0]["score"] == 0.0


def test_official_sdk_rejects_missing_document_name():
    from hr_agent.knowledge.backend import KnowledgeBackendError

    client = FakeVikingClient({"col-policy": _response({
        "content": "正文", "doc_info": {}, "score": 0.4,
    })})

    with pytest.raises(KnowledgeBackendError) as exc_info:
        _backend(client).search("迟到扣款", scope="policy", top_k=5)

    assert exc_info.value.error_type == "knowledge_source_missing"


def test_official_sdk_scope_all_merges_three_collections_without_childcare():
    client = FakeVikingClient({
        "col-policy": _response(_row(content="p", source="p.md", score=0.1)),
        "col-handbook": _response(_row(content="h", source="h.md", score=0.2)),
        "col-salary": _response(_row(content="s", source="s.md", score=0.3)),
    })
    r = _backend(client).search("x", scope="all", top_k=5)

    assert [c["collection_name"] for c in client.calls] == [
        "col-policy", "col-handbook", "col-salary",
    ]
    assert len(r) == 3
    assert {x["content"] for x in r} == {"p", "h", "s"}
    assert "col-childcare" not in {c["collection_name"] for c in client.calls}


def test_official_sdk_all_returns_successes_and_marks_partial_failure():
    client = FakeVikingClient({
        "col-policy": ConnectionError("network down"),
        "col-handbook": _response(_row(content="h", source="h.md", score=0.2)),
        "col-salary": _response(_row(content="s", source="s.md", score=0.3)),
    })
    b = _backend(client)
    r = b.search("x", scope="all", top_k=5)

    assert len(r) == 2
    assert r.partial_failure is True
    assert r.failed_scopes == ("policy",)


def test_official_sdk_distinguishes_empty_result_from_single_scope_failure():
    from hr_agent.knowledge.backend import KnowledgeBackendError

    empty = _backend(FakeVikingClient({"col-policy": _response()}))
    assert empty.search("none", scope="policy", top_k=5) == []

    failed = _backend(FakeVikingClient({
        "col-policy": ConnectionError("network down"),
    }))
    with pytest.raises(KnowledgeBackendError) as exc_info:
        failed.search("none", scope="policy", top_k=5)
    assert exc_info.value.error_type == "knowledge_network_error"


def test_official_sdk_retries_qps_once_without_changing_results():
    sleeps = []
    client = FakeVikingClient({
        "col-policy": [RuntimeError("QPS limit exceeded"), _response(_row())],
    })

    r = _backend(client, sleep=lambda seconds: sleeps.append(seconds)).search(
        "迟到扣款", scope="policy", top_k=5
    )

    assert len(client.calls) == 2
    assert sleeps == [1.2]
    assert r[0]["score"] == 0.92


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        (RuntimeError("SignatureDoesNotMatch"), "knowledge_authentication_failed"),
        (ConnectionError("connection reset"), "knowledge_network_error"),
    ],
)
def test_official_sdk_classifies_safe_errors(error, expected_type):
    from hr_agent.knowledge.backend import KnowledgeBackendError

    client = FakeVikingClient({"col-policy": error})

    with pytest.raises(KnowledgeBackendError) as exc_info:
        _backend(client).search("x", scope="policy", top_k=5)

    assert exc_info.value.error_type == expected_type
    assert "SignatureDoesNotMatch" not in str(exc_info.value)
    assert "connection reset" not in str(exc_info.value)


@pytest.mark.parametrize(
    "response",
    [None, {}, {"result_list": "not-a-list"}, _response({"content": "x"})],
)
def test_official_sdk_rejects_invalid_response(response):
    from hr_agent.knowledge.backend import KnowledgeBackendError

    client = FakeVikingClient({"col-policy": response})

    with pytest.raises(KnowledgeBackendError) as exc_info:
        _backend(client).search("x", scope="policy", top_k=5)

    assert exc_info.value.error_type == "knowledge_invalid_response"


def test_official_sdk_emits_non_sensitive_knowledge_span_attributes():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test-knowledge")
    client = FakeVikingClient({"col-policy": _response(_row())})

    _backend(client, tracer=tracer).search("敏感查询正文", scope="policy", top_k=5)

    span = exporter.get_finished_spans()[-1]
    assert span.name == "knowledge.search"
    assert span.attributes["knowledge.scope"] == "policy"
    assert span.attributes["knowledge.collection"] == "col-policy"
    assert span.attributes["knowledge.top_k"] == 5
    assert span.attributes["knowledge.result_count"] == 1
    assert span.attributes["knowledge.partial_failure"] is False
    assert span.attributes["knowledge.error_type"] == "none"
    assert span.attributes["knowledge.elapsed_ms"] >= 0
    assert "敏感查询正文" not in str(span.attributes)
