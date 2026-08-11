"""Narrow cross-Runtime document context carried in A2A context_summary."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError


_PREFIX = "hr-document-v1:"
_SENSITIVE = re.compile(
    r"client_secret|grant_type|authorization\s*:|bearer\s+|"
    r"volcengine_(?:access|secret)_key|model_agent_api_key|runtime_api_key|"
    r"gaia\s*_?jwt|\b(?:ak|sk)\s*[:=]|api[_ -]?key\s*[:=]|"
    r"employee\s*_?id|target_employee_id|corp_id",
    re.IGNORECASE,
)


class DocumentContextError(ValueError):
    """The allowlisted document context is missing, malformed, or unsafe."""


class DocumentContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1, max_length=2048)
    content: str = Field(min_length=1, max_length=30000)


def _validate(payload: object) -> DocumentContext:
    try:
        context = DocumentContext.model_validate(payload)
    except ValidationError:
        raise DocumentContextError("document_context_invalid") from None
    parsed = urlparse(context.url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        raise DocumentContextError("document_context_invalid")
    if _SENSITIVE.search(context.url) or _SENSITIVE.search(context.content):
        raise DocumentContextError("document_context_sensitive")
    return context


def encode_document_context(payload: object) -> str:
    context = _validate(payload)
    return _PREFIX + json.dumps(
        context.model_dump(), ensure_ascii=False, separators=(",", ":")
    )


def decode_document_context(value: str) -> DocumentContext | None:
    if not value or not value.startswith(_PREFIX):
        return None
    try:
        payload = json.loads(value.removeprefix(_PREFIX))
    except (TypeError, json.JSONDecodeError):
        raise DocumentContextError("document_context_invalid") from None
    return _validate(payload)


def session_document_context(state: object, message: str) -> str:
    """Extract only a matching document payload; never serialize session state."""
    if not isinstance(state, dict):
        return ""
    payload = state.get("document_context")
    if not isinstance(payload, dict):
        return ""
    context = _validate(payload)
    if context.url not in message:
        return ""
    return encode_document_context(context.model_dump())
