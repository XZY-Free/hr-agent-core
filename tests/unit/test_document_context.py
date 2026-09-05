import json

import pytest

from packages.hr_domain.documents.context import (
    DocumentContextError,
    decode_document_context,
    encode_document_context,
    session_document_context,
)


def test_document_context_round_trip_only_contains_required_safe_fields():
    encoded = encode_document_context({
        "documents": [{
            "canonical_reference": "ref-1",
            "url": "https://example.com/notice.docx",
            "content": "春节值班安排",
        }]
    })

    decoded = decode_document_context(encoded)
    item = decoded.documents[0]
    assert item.canonical_reference == "ref-1"
    assert item.url == "https://example.com/notice.docx"
    assert item.content == "春节值班安排"
    assert set(json.loads(encoded.removeprefix("hr-document-v1:"))) == {"documents"}


def test_session_document_context_ignores_unrelated_state_and_requires_message_url():
    state = {
        "employeeId": "must-not-cross-runtime",
        "client_secret": "must-not-cross-runtime",
        "document_context": {
            "url": "https://example.com/notice.docx",
            "content": "春节值班安排",
        },
    }

    encoded = session_document_context(
        state, "https://example.com/notice.docx 这份文件说了什么"
    )

    assert "employeeId" not in encoded
    assert "client_secret" not in encoded
    assert session_document_context(state, "迟到扣款制度") == ""
    # 现有 session 源 {url, content} 被翻译为 envelope。
    item = json.loads(encoded.removeprefix("hr-document-v1:"))["documents"][0]
    assert item["url"] == "https://example.com/notice.docx"
    assert item["content"] == "春节值班安排"


@pytest.mark.parametrize(
    "payload",
    [
        {"documents": [{"canonical_reference": "r", "url": "file:///tmp/notice.docx", "content": "safe"}]},
        {"documents": [{"canonical_reference": "r", "url": "https://example.com/notice.docx", "content": "Authorization: Bearer x"}]},
        {"documents": [{"canonical_reference": "r", "url": "https://example.com/notice.docx", "content": ""}]},
        {"documents": [{"canonical_reference": "r", "url": "https://example.com/notice.docx", "content": "x" * 30001}]},
    ],
)
def test_document_context_rejects_paths_credentials_empty_and_oversize(payload):
    with pytest.raises(DocumentContextError):
        encode_document_context(payload)
