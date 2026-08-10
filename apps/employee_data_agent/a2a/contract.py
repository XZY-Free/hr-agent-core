"""Employee Data业务请求与结构化结果契约。"""

from typing import Literal

from a2a.types import Message, Part
from pydantic import BaseModel, ConfigDict

from apps.employee_data_agent.a2a.card import AGENT_NAME, AGENT_VERSION
from packages.agent_runtime.a2a.artifact import structured_result_parts
from packages.agent_runtime.a2a.context import (
    A2ARequestContext,
    RequestContractError,
    parse_request,
)


EmployeeDataStatus = Literal[
    "succeeded", "not_found", "rejected", "temporarily_unavailable", "failed"
]


class EmployeeDataA2ARequest(A2ARequestContext):
    """Employee Data复用通用A2A上下文。"""


class EmployeeDataA2AResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    status: EmployeeDataStatus
    answer: str
    query_type: str
    data: dict | None = None
    data_as_of: str
    source: str | None = None
    employee_ref: str | None = None
    partial: bool = False
    agent_name: Literal["hr-employee-data-agent"] = AGENT_NAME
    agent_version: Literal["1.0.0"] = AGENT_VERSION
    error_code: str | None = None
    retryable: bool = False


def parse_employee_data_request(message: Message | None) -> EmployeeDataA2ARequest:
    return parse_request(message, EmployeeDataA2ARequest)


def result_parts(result: EmployeeDataA2AResult) -> list[Part]:
    return structured_result_parts(result.answer, result.model_dump(mode="json"))
