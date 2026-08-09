"""Consult A2A Message和Artifact公开契约测试。"""

from uuid import uuid4

import pytest
from a2a.types import DataPart, Message, Part, Role, TextPart

from apps.consult_agent.a2a.contract import (
    ConsultA2AResult,
    RequestContractError,
    parse_consult_request,
    result_parts,
)


def _message(*, metadata=None, text="迟到扣款制度是什么") -> Message:
    return Message(
        role=Role.user,
        message_id=str(uuid4()),
        context_id="session-a",
        metadata=metadata or {
            "request_id": "request-a",
            "user_id": "user-a",
            "session_id": "session-a",
            "caller_agent": "hr_orchestrator",
            "locale": "zh-CN",
            "context_summary": "用户正在咨询考勤制度",
        },
        parts=[Part(root=TextPart(text=text))],
    )


def test_parse_request_uses_message_and_strict_metadata_allowlist():
    request = parse_consult_request(_message())
    assert request.request_id == "request-a"
    assert request.user_id == "user-a"
    assert request.session_id == "session-a"
    assert request.caller_agent == "hr_orchestrator"
    assert request.locale == "zh-CN"
    assert request.message == "迟到扣款制度是什么"
    assert request.context_summary == "用户正在咨询考勤制度"


@pytest.mark.parametrize(
    "metadata_patch",
    [
        {"request_id": None},
        {"caller_agent": "unknown_agent"},
        {"locale": "en-US"},
        {"client_secret": "must-not-propagate"},
    ],
)
def test_invalid_or_unknown_request_metadata_fails_closed(metadata_patch):
    metadata = dict(_message().metadata)
    metadata.update(metadata_patch)
    with pytest.raises(RequestContractError, match="A2A请求字段无效"):
        parse_consult_request(_message(metadata=metadata))


@pytest.mark.parametrize(
    "text",
    [
        "client_secret=must-not-propagate",
        "Authorization: Bearer must-not-propagate",
        "VOLCENGINE_SECRET_KEY=must-not-propagate",
        "AK=must-not-propagate",
        "SK: must-not-propagate",
    ],
)
def test_sensitive_content_is_rejected_before_agent_input(text):
    with pytest.raises(RequestContractError, match="A2A请求包含禁止内容"):
        parse_consult_request(_message(text=text))


def test_result_parts_include_user_text_and_structured_data_without_content_chunks():
    result = ConsultA2AResult(
        request_id="request-a",
        status="succeeded",
        answer="迟到按制度分段扣款。",
        question_category="attendance_policy",
        knowledge_scope="policy",
        sources=[{"source": "考勤制度.docx", "score": 0.0}],
        truncated=False,
        recommend_hr=False,
        error_code=None,
    )

    parts = result_parts(result)

    assert isinstance(parts[0].root, TextPart)
    assert parts[0].root.text == result.answer
    assert isinstance(parts[1].root, DataPart)
    assert parts[1].root.data == result.model_dump()
    serialized = str(parts[1].root.data)
    assert "知识切片正文" not in serialized
    assert parts[1].root.data["sources"][0]["score"] == 0.0
