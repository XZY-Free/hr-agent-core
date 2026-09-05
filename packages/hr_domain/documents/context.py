"""Narrow cross-Runtime document context carried in A2A context_summary.

The wire format is a single `hr-document-v1:` prefix followed by compact JSON
`{"documents":[...]}`. Each document item carries a required
`canonical_reference` plus an optional safe http(s) `url` and/or sanitized
`content`; at least one of url/content is required. Text-only and URL-only
sources are both expressible without inventing a URL or a placeholder, and up
to `MAX_DOCUMENTS` items are allowed. Sensitive/credential/localhost forms are
rejected without echoing input content.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError


_PREFIX = "hr-document-v1:"
MAX_DOCUMENTS = 5
MAX_DOCUMENT_CONTENT = 30000
MAX_TOTAL_CONTENT = 60000
_MAX_REFERENCE = 256
_SENSITIVE = re.compile(
    r"client_secret|grant_type|authorization\s*:|bearer\s+|"
    r"volcengine_(?:access|secret)_key|model_agent_api_key|runtime_api_key|"
    r"gaia\s*_?jwt|\b(?:ak|sk)\s*[:=]|api[-_ ]?key\s*[:=]|"
    r"employee\s*_?id|target_employee_id|corp_id",
    re.IGNORECASE,
)
# C0 控制字符与 DEL：可破坏机器生成的证据分隔块（CR/LF/控制符）。
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class DocumentContextError(ValueError):
    """The allowlisted document context is missing, malformed, or unsafe.

    `code` is a stable machine code used by callers to map to attachment
    failures without echoing input content.
    """

    def __init__(self, code: str, message: str = "文档上下文不合法。"):
        super().__init__(message)
        self.code = code
        self.message = message


class DocumentItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_reference: str = Field(min_length=1, max_length=_MAX_REFERENCE)
    display_name: str | None = Field(default=None, max_length=256)
    media_type: str | None = Field(default=None, max_length=128)
    url: str | None = Field(default=None, max_length=2048)
    content: str | None = Field(default=None, max_length=100000)


class DocumentEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    documents: list[DocumentItem] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 语义校验（返回精确 code，不把输入回显进异常）
# --------------------------------------------------------------------------
def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.hostname in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
        or (parsed.hostname or "").lower().endswith(".local")
    ):
        raise DocumentContextError("document_context_url_invalid", "文档链接不合法。")
    if _SENSITIVE.search(url):
        raise DocumentContextError("document_context_sensitive", "文档链接包含敏感内容。")


def _validate_reference(value: str) -> None:
    """canonical_reference 必须是安全的短引用，不得成为注入/路径/凭据载体。"""
    if _CONTROL.search(value):
        raise DocumentContextError("document_context_invalid", "文档引用含非法控制字符。")
    if value.startswith(("/", "\\")) or "file://" in value or ".." in value:
        raise DocumentContextError("document_context_invalid", "文档引用形态不合法。")
    if _SENSITIVE.search(value):
        raise DocumentContextError("document_context_sensitive", "文档引用包含敏感内容。")


def _validate(payload: object) -> DocumentEnvelope:
    try:
        envelope = DocumentEnvelope.model_validate(payload)
    except ValidationError:
        raise DocumentContextError("document_context_invalid") from None
    if not envelope.documents:
        raise DocumentContextError("document_context_invalid")
    if len(envelope.documents) > MAX_DOCUMENTS:
        raise DocumentContextError("document_context_too_many", "文档数量超出上限。")
    total = 0
    for item in envelope.documents:
        _validate_reference(item.canonical_reference)
        if not item.url and not item.content:
            raise DocumentContextError(
                "document_context_invalid", "文档缺少 url 或 content。"
            )
        if item.display_name is not None:
            if _CONTROL.search(item.display_name):
                raise DocumentContextError(
                    "document_context_invalid", "文档显示名含非法控制字符。"
                )
            if _SENSITIVE.search(item.display_name):
                raise DocumentContextError(
                    "document_context_sensitive", "文档显示名包含敏感内容。"
                )
        if item.media_type is not None:
            if _CONTROL.search(item.media_type):
                raise DocumentContextError(
                    "document_context_invalid", "文档媒体类型含非法控制字符。"
                )
            if _SENSITIVE.search(item.media_type):
                raise DocumentContextError(
                    "document_context_sensitive", "文档媒体类型包含敏感内容。"
                )
        if item.content is not None:
            if not item.content.strip():
                raise DocumentContextError("document_context_invalid", "文档内容为空。")
            if _SENSITIVE.search(item.content):
                raise DocumentContextError(
                    "document_context_sensitive", "文档内容包含敏感内容。"
                )
            if len(item.content) > MAX_DOCUMENT_CONTENT:
                raise DocumentContextError(
                    "document_context_too_large", "单个文档内容过大。"
                )
            total += len(item.content)
        if item.url is not None:
            _check_url(item.url)
    if total > MAX_TOTAL_CONTENT:
        raise DocumentContextError("document_context_too_large", "文档内容总量过大。")
    return envelope


def encode_document_context(payload: object) -> str:
    envelope = _validate(payload)
    return _PREFIX + json.dumps(
        envelope.model_dump(), ensure_ascii=False, separators=(",", ":")
    )


def decode_document_context(value: str) -> DocumentEnvelope | None:
    if not value or not value.startswith(_PREFIX):
        return None
    try:
        payload = json.loads(value.removeprefix(_PREFIX))
    except (TypeError, json.JSONDecodeError):
        raise DocumentContextError("document_context_invalid") from None
    return _validate(payload)


def session_document_context(state: object, message: str) -> str:
    """Translate an existing session `{url, content}` source into the new envelope.

    Never serialize session state. The caller supplies the original user message;
    a matching URL document is carried only for that scoped turn.
    """
    if not isinstance(state, dict):
        return ""
    payload = state.get("document_context")
    if not isinstance(payload, dict):
        return ""
    url = payload.get("url")
    content = payload.get("content")
    if not isinstance(url, str) or not url:
        return ""
    envelope = {
        "documents": [
            {
                "canonical_reference": url,
                "url": url,
                "content": content if isinstance(content, str) and content else None,
            }
        ]
    }
    context = _validate(envelope)
    if url not in message:
        return ""
    return encode_document_context(envelope)
