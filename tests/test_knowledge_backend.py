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


def test_agentkit_search_raises_not_implemented():
    from hr_agent.knowledge.agentkit_backend import AgentKitKnowledgeBackend

    b = AgentKitKnowledgeBackend(
        collection_map={
            "policy": "col-policy",
            "handbook": "col-handbook",
            "salary": "col-salary",
            "childcare": "col-childcare",
        }
    )
    with pytest.raises(NotImplementedError) as exc_info:
        b.search("test", scope="policy")
    assert "待接入" in str(exc_info.value)
