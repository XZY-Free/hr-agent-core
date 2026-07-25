"""kb_search 工具测试。"""
import pytest

from hr_agent.tools.rules.kb_search import kb_search


class FakeContext:
    state = {}


def test_kb_search_normal_hit():
    ctx = FakeContext()
    r = kb_search("迟到扣款", scope="policy", tool_context=ctx)
    assert r["success"] is True
    assert len(r["data"]) > 0
    assert "五十元" in r["data"][0]["content"]
    assert r["data"][0]["source"] == "policy.md"


def test_kb_search_empty_result():
    ctx = FakeContext()
    r = kb_search("xyz_not_exist", scope="policy", tool_context=ctx)
    assert r["success"] is True
    assert r["data"] == []


def test_kb_search_invalid_scope():
    ctx = FakeContext()
    r = kb_search("test", scope="invalid", tool_context=ctx)
    assert r["success"] is False
    assert r["error_type"] == "invalid_scope"
    assert "scope" in r["message"]


def test_kb_search_backend_exception(monkeypatch):
    ctx = FakeContext()

    def _raise(*args, **kwargs):
        raise NotImplementedError("agentkit not ready")

    monkeypatch.setattr(
        "hr_agent.tools.rules.kb_search.get_backend",
        lambda: type("BadBackend", (), {"search": _raise})(),
    )
    r = kb_search("test", scope="policy", tool_context=ctx)
    assert r["success"] is False
    assert r["error_type"] == "kb_unavailable"
    assert "暂不可用" in r["message"]
