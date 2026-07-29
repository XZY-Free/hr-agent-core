"""KnowledgeBackend 抽象层与本地桩测试。"""
import os

import pytest

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


# ---------- Task 2: AgentKit 真库 backend 占位 ----------


def test_factory_returns_agentkit_when_env_set(monkeypatch):
    from hr_agent.knowledge.agentkit_backend import AgentKitKnowledgeBackend

    monkeypatch.setenv("KB_BACKEND", "agentkit")
    monkeypatch.setenv("KB_COLLECTION_POLICY", "col-policy")
    monkeypatch.setenv("KB_COLLECTION_HANDBOOK", "col-handbook")
    monkeypatch.setenv("KB_COLLECTION_SALARY", "col-salary")
    monkeypatch.setenv("KB_COLLECTION_CHILDCARE", "col-childcare")
    b = get_backend()
    assert isinstance(b, AgentKitKnowledgeBackend)


def test_agentkit_search_converts_entries(monkeypatch):
    """真库检索：挂桩 _search_raw，验证原始 result_list → {content,source,score} 转换。"""
    from hr_agent.knowledge import agentkit_backend
    from hr_agent.knowledge.agentkit_backend import AgentKitKnowledgeBackend

    def fake_search_raw(kb, collection, query, top_k):
        return [{"content": "迟到扣款五十元", "source": "考勤制度.md", "score": 0.92}]

    monkeypatch.setattr(agentkit_backend, "_search_raw", fake_search_raw)
    monkeypatch.setattr(agentkit_backend, "_get_kb", lambda c: object())
    monkeypatch.setattr(agentkit_backend, "_KB_CACHE", {})

    b = AgentKitKnowledgeBackend(
        collection_map={
            "policy": "col-policy",
            "handbook": "col-handbook",
            "salary": "col-salary",
            "childcare": "col-childcare",
        }
    )
    r = b.search("迟到扣款", scope="policy", top_k=5)
    assert r and r[0]["content"] == "迟到扣款五十元"
    assert r[0]["source"] == "考勤制度.md"
    assert r[0]["score"] == 0.92


def test_agentkit_scope_all_merges_three_libs(monkeypatch):
    """scope=all 应检索 policy+handbook+salary 三库（不含 childcare）。"""
    from hr_agent.knowledge import agentkit_backend
    from hr_agent.knowledge.agentkit_backend import AgentKitKnowledgeBackend

    called = []

    def fake_search_raw(kb, collection, query, top_k):
        called.append(collection)
        return [{"content": f"hit@{collection}", "source": collection, "score": 0.0}]

    monkeypatch.setattr(agentkit_backend, "_search_raw", fake_search_raw)
    monkeypatch.setattr(agentkit_backend, "_get_kb", lambda c: object())
    monkeypatch.setattr(agentkit_backend, "_KB_CACHE", {})

    b = AgentKitKnowledgeBackend(collection_map={
        "policy": "p", "handbook": "h", "salary": "s", "childcare": "c"})
    r = b.search("x", scope="all", top_k=5)

    assert called == ["p", "h", "s"]          # 只查三库，不含 childcare
    assert len(r) == 3
    assert {x["content"] for x in r} == {"hit@p", "hit@h", "hit@s"}


def test_agentkit_search_swallows_single_lib_failure(monkeypatch):
    """单库检索异常不阻断其他库。"""
    from hr_agent.knowledge import agentkit_backend
    from hr_agent.knowledge.agentkit_backend import AgentKitKnowledgeBackend

    def fake_search_raw(kb, collection, query, top_k):
        if collection == "p":
            raise RuntimeError("viking auth failed")
        return [{"content": "ok", "source": collection, "score": 0.0}]

    monkeypatch.setattr(agentkit_backend, "_search_raw", fake_search_raw)
    monkeypatch.setattr(agentkit_backend, "_get_kb", lambda c: object())
    monkeypatch.setattr(agentkit_backend, "_KB_CACHE", {})

    b = AgentKitKnowledgeBackend(collection_map={
        "policy": "p", "handbook": "h", "salary": "s", "childcare": "c"})
    r = b.search("x", scope="all", top_k=5)
    assert len(r) == 2                        # policy 失败，handbook+salary 仍返回
