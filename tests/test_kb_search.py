"""kb_search 工具测试。"""
import pytest

from hr_agent.tools.rules.kb_search import kb_search


class FakeContext:
    state = {}


@pytest.fixture
def stub_backend(monkeypatch):
    """强制走本地桩后端，不依赖全局 .env 的 KB_BACKEND（真库模式下单测仍测桩行为）。"""
    from hr_agent.knowledge.local_stub import LocalStubBackend

    monkeypatch.setattr(
        "hr_agent.tools.rules.kb_search.get_backend", lambda: LocalStubBackend()
    )


def test_kb_search_normal_hit(stub_backend):
    ctx = FakeContext()
    r = kb_search("迟到扣款", scope="policy", tool_context=ctx)
    assert r["success"] is True
    assert len(r["data"]) > 0
    assert "五十元" in r["data"][0]["content"]
    assert r["data"][0]["source"] == "policy.md"


def test_kb_search_empty_result(stub_backend):
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
