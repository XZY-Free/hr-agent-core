"""WP-06 公共附件解析边界测试。"""

import pytest

from apps.orchestrator.public_runtime.attachments import (
    AccessMode,
    AttachmentResolutionError,
    AttachmentResolver,
    ResolvedAttachment,
)
from apps.orchestrator.public_runtime.request import AttachmentReference


def _ref(**kw):
    base = {"reference_id": "ref-1", "resource_type": "web_document",
            "display_name": "公告.docx", "media_type": "application/pdf"}
    base.update(kw)
    return AttachmentReference(**base)


def _text_resolver(ref):
    return ResolvedAttachment(
        canonical_reference=ref.reference_id, resource_type=ref.resource_type,
        media_type=ref.media_type, display_name=ref.display_name,
        access_mode=AccessMode.TEXT, text="春节值班安排内容",
    )


def _url_resolver(ref):
    return ResolvedAttachment(
        canonical_reference=ref.reference_id, resource_type=ref.resource_type,
        media_type=ref.media_type, display_name=ref.display_name,
        access_mode=AccessMode.URL,
        url="https://docs.example.com/notice.docx",
    )


def test_no_attachments_returns_empty():
    assert AttachmentResolver().resolve_all(None) == []


def test_supported_text_reference_resolves():
    resolver = AttachmentResolver(resolvers={"web_document": _text_resolver})
    result = resolver.resolve_all([_ref()])
    assert len(result) == 1
    assert result[0].access_mode is AccessMode.TEXT
    assert result[0].text == "春节值班安排内容"


def test_supported_url_reference_resolves():
    resolver = AttachmentResolver(resolvers={"web_document": _url_resolver})
    result = resolver.resolve_all([_ref()])
    assert result[0].access_mode is AccessMode.URL
    assert result[0].url == "https://docs.example.com/notice.docx"


def test_unsupported_resource_type_explicit_error():
    resolver = AttachmentResolver()
    with pytest.raises(AttachmentResolutionError) as exc:
        resolver.resolve_all([_ref(resource_type="snowharness_file")])
    assert exc.value.error_code == "attachment_type_not_supported"


def test_no_resolver_fails_closed_not_ignored():
    resolver = AttachmentResolver()
    with pytest.raises(AttachmentResolutionError) as exc:
        resolver.resolve_all([_ref()])
    assert exc.value.error_code == "attachment_not_resolvable"
    assert "暂时无法读取" in exc.value.message


def test_limit_exceeded():
    refs = [_ref(reference_id=f"r-{i}") for i in range(6)]
    with pytest.raises(AttachmentResolutionError) as exc:
        AttachmentResolver().resolve_all(refs)
    assert exc.value.error_code == "attachment_limit_exceeded"


def test_five_allowed():
    refs = [_ref(reference_id=f"r-{i}") for i in range(5)]
    resolver = AttachmentResolver(resolvers={"web_document": _text_resolver})
    assert len(resolver.resolve_all(refs)) == 5


def test_local_path_reference_rejected_at_schema():
    # AttachmentReference 自身拒绝本地路径形态（request.py 校验）。
    with pytest.raises(Exception):
        _ref(reference_id="/etc/passwd")


def test_file_url_reference_rejected_at_schema():
    with pytest.raises(Exception):
        _ref(reference_id="file:///etc/passwd")


def test_url_with_credentials_rejected():
    resolver = AttachmentResolver(resolvers={"web_document": lambda r: ResolvedAttachment(
        canonical_reference=r.reference_id, resource_type=r.resource_type,
        media_type=r.media_type, display_name=r.display_name,
        access_mode=AccessMode.URL,
        url="https://user:pass@example.com/doc.docx")})
    with pytest.raises(AttachmentResolutionError) as exc:
        resolver.resolve_all([_ref()])
    assert exc.value.error_code == "attachment_invalid"


def test_localhost_url_rejected():
    resolver = AttachmentResolver(resolvers={"web_document": lambda r: ResolvedAttachment(
        canonical_reference=r.reference_id, resource_type=r.resource_type,
        media_type=r.media_type, display_name=r.display_name,
        access_mode=AccessMode.URL, url="http://localhost:8000/doc")})
    with pytest.raises(AttachmentResolutionError) as exc:
        resolver.resolve_all([_ref()])
    assert exc.value.error_code == "attachment_invalid"


def test_sensitive_content_rejected():
    resolver = AttachmentResolver(resolvers={"web_document": lambda r: ResolvedAttachment(
        canonical_reference=r.reference_id, resource_type=r.resource_type,
        media_type=r.media_type, display_name=r.display_name,
        access_mode=AccessMode.TEXT, text="client_secret=abc123")})
    with pytest.raises(AttachmentResolutionError) as exc:
        resolver.resolve_all([_ref()])
    assert exc.value.error_code == "attachment_sensitive"


def test_too_large_text_rejected():
    big = "a" * 30001
    resolver = AttachmentResolver(resolvers={"web_document": lambda r: ResolvedAttachment(
        canonical_reference=r.reference_id, resource_type=r.resource_type,
        media_type=r.media_type, display_name=r.display_name,
        access_mode=AccessMode.TEXT, text=big)})
    with pytest.raises(AttachmentResolutionError) as exc:
        resolver.resolve_all([_ref()])
    assert exc.value.error_code == "attachment_too_large"


# ---------- runtime 集成 ----------


@pytest.mark.asyncio
async def test_runtime_fails_closed_when_attachment_not_resolvable(monkeypatch):
    """附件不可解析时返回明确错误，绝不调用模型去猜。"""
    from apps.orchestrator.public_runtime.runtime import HrAssistantRuntime
    from apps.orchestrator.public_runtime.result import HrAssistantResult

    class _Runner:
        async def run(self, **kwargs):
            raise AssertionError("附件不可解析时不得调用模型")

    class _Router:
        async def route(self, *a, **k):
            raise AssertionError("附件不可解析时不得远程路由")

    runtime = HrAssistantRuntime(remote_router=_Router(), local_runner=_Runner())
    result = await runtime.invoke({
        "request_id": "req-a",
        "message": "帮我处理这个附件",
        "context_id": "ctx-a",
        "context": {"attachment_references": [
            {"reference_id": "ref-1", "resource_type": "snowharness_file"}
        ]},
    })
    assert isinstance(result, HrAssistantResult)
    assert result.error_code in ("attachment_not_resolvable", "attachment_type_not_supported")


@pytest.mark.asyncio
async def test_runtime_resolved_url_attachment_passes_doc_context_to_consult():
    """解出合法 URL 的附件 → 传给远程 Consult 的文档上下文（DocumentContext）。"""
    from apps.orchestrator.public_runtime.runtime import HrAssistantRuntime
    from apps.orchestrator.a2a.router import RemoteRouteResponse
    from packages.hr_domain.documents.context import decode_document_context

    captured = {}

    class _Runner:
        async def run(self, **kwargs):
            raise AssertionError("应路由到远程 Consult")

    class _Router:
        async def route(self, payload, *, attachment_context_summary=None):
            captured["summary"] = attachment_context_summary
            return RemoteRouteResponse(
                answer="文档回答了你的问题", request_id="inner-1",
                target="hr-consult-agent", status="succeeded")

    runtime = HrAssistantRuntime(
        remote_router=_Router(), local_runner=_Runner(),
        attachment_resolver=AttachmentResolver(resolvers={"web_document": lambda r:
            ResolvedAttachment(
                canonical_reference=r.reference_id, resource_type=r.resource_type,
                media_type=r.media_type, display_name=r.display_name,
                access_mode=AccessMode.URL,
                url="https://docs.example.com/notice.docx")}),
    )
    result = await runtime.invoke({
        "request_id": "req-a",
        "message": "这份文件说了什么",
        "context_id": "ctx-a",
        "context": {"attachment_references": [
            {"reference_id": "ref-1", "resource_type": "web_document",
             "display_name": "公告.docx", "media_type": "application/pdf"}
        ]},
    })
    assert result.status == "completed"
    assert captured["summary"]
    ctx = decode_document_context(captured["summary"])
    assert ctx is not None
    assert ctx.url == "https://docs.example.com/notice.docx"
    assert "employeeId" not in captured["summary"]
