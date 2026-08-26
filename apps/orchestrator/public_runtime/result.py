"""顶层统一公共结果对象：内部结果进入 public result mapper 后的稳定输出。"""

from pydantic import BaseModel, ConfigDict, Field

from apps.orchestrator.public_contract.identity import (
    PUBLIC_AGENT_ID,
    PUBLIC_AGENT_VERSION,
)

PUBLIC_STATUSES = (
    "completed",
    "input_required",
    "rejected",
    "failed",
    "cancelled",
)


class HrAssistantResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    status: str
    answer: str
    result_type: str = "conversation"
    data: dict | None = None
    actions: list = Field(default_factory=list)
    error_code: str | None = None
    retryable: bool = False
    agent_name: str = PUBLIC_AGENT_ID
    agent_version: str = PUBLIC_AGENT_VERSION

    def to_payload(self) -> dict:
        return self.model_dump(exclude_none=False)


def completed(
    *,
    request_id: str,
    answer: str,
    result_type: str = "conversation",
    data: dict | None = None,
) -> HrAssistantResult:
    return HrAssistantResult(
        request_id=request_id,
        status="completed",
        answer=answer,
        result_type=result_type,
        data=data,
    )


def input_required(*, request_id: str, answer: str) -> HrAssistantResult:
    return HrAssistantResult(
        request_id=request_id,
        status="input_required",
        answer=answer,
        result_type="missing_information",
        error_code="input_required",
    )


def rejected(
    *, request_id: str, answer: str, error_code: str
) -> HrAssistantResult:
    return HrAssistantResult(
        request_id=request_id,
        status="rejected",
        answer=answer,
        result_type="error",
        error_code=error_code,
    )


def failed(
    *,
    request_id: str,
    answer: str,
    error_code: str,
    retryable: bool = True,
) -> HrAssistantResult:
    return HrAssistantResult(
        request_id=request_id,
        status="failed",
        answer=answer,
        result_type="error",
        error_code=error_code,
        retryable=retryable,
    )
