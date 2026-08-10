"""Employee Data A2A请求与结构化Artifact契约。"""

from uuid import uuid4

import pytest
from a2a.types import DataPart, Message, Part, Role, TextPart

from apps.employee_data_agent.a2a.contract import (
    EmployeeDataA2AResult,
    RequestContractError,
    parse_employee_data_request,
    result_parts,
)


def _message(*, metadata_patch=None, text="我还有几天年假") -> Message:
    metadata = {
        "request_id": "request-employee-a",
        "user_id": "user-alpha",
        "session_id": "session-alpha",
        "caller_agent": "hr_orchestrator",
        "locale": "zh-CN",
        "context_summary": "",
    }
    if metadata_patch:
        metadata.update(metadata_patch)
    return Message(
        role=Role.user,
        message_id=str(uuid4()),
        context_id="session-alpha",
        metadata=metadata,
        parts=[Part(root=TextPart(text=text))],
    )


def test_request_contains_only_common_context_and_message():
    request = parse_employee_data_request(_message())
    assert request.model_dump() == {
        "request_id": "request-employee-a",
        "user_id": "user-alpha",
        "session_id": "session-alpha",
        "caller_agent": "hr_orchestrator",
        "locale": "zh-CN",
        "message": "我还有几天年假",
        "context_summary": "",
    }


@pytest.mark.parametrize("field", ["employeeId", "target_employee_id", "corp_id"])
def test_identity_or_credential_fields_fail_before_agent(field):
    with pytest.raises(RequestContractError, match="A2A请求字段无效"):
        parse_employee_data_request(_message(metadata_patch={field: "forbidden"}))


@pytest.mark.parametrize(
    "text",
    [
        "employeeId=EMP-001",
        "target_employee_id: EMP-002",
        "client_secret=forbidden",
        "Authorization: Bearer forbidden",
    ],
)
def test_sensitive_content_fails_before_agent(text):
    with pytest.raises(RequestContractError, match="A2A请求包含禁止内容"):
        parse_employee_data_request(_message(text=text))


def test_artifact_has_fixed_fields_and_no_raw_employee_id():
    result = EmployeeDataA2AResult(
        request_id="request-employee-a",
        status="succeeded",
        answer="您的年休假余额为4天。",
        query_type="leave_balance",
        data={"remain": 4},
        data_as_of="2026-08-09T12:00:00+00:00",
        source="stub",
        employee_ref="empref_opaque",
        partial=False,
        error_code=None,
        retryable=False,
    )
    parts = result_parts(result)
    assert isinstance(parts[0].root, TextPart)
    assert isinstance(parts[1].root, DataPart)
    assert set(parts[1].root.data) == {
        "request_id", "status", "answer", "query_type", "data",
        "data_as_of", "source", "employee_ref", "partial", "agent_name",
        "agent_version", "error_code", "retryable",
    }
    serialized = str(parts[1].root.data)
    assert "employeeId" not in serialized
    assert "EMP-" not in serialized
