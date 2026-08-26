"""公共请求语义对象：SnowHarness → 企业人力智能助手 的唯一入口载荷。

不是内部 A2ARequestContext 的别名；禁止 employee_id / corp_id / 内部凭据。
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.agent_runtime.a2a.context import contains_sensitive_data
from apps.orchestrator.public_contract.invocation_context import (
    ALLOWED_CONTEXT_KEYS,
)

SUPPORTED_LOCALES = ("zh-CN",)


class PublicRequestError(Exception):
    """公共请求校验失败，携带稳定机器错误码。"""

    def __init__(self, error_code: str, message: str = "公共请求不符合合同。"):
        super().__init__(message)
        self.error_code = error_code


class ExecutionSubject(BaseModel):
    """SnowHarness 本次执行所代表的可信调用者身份。

    subject_kind 只描述平台主体类型；不携带任何 HR 业务主键。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str = Field(min_length=1, max_length=128)
    subject_kind: str = Field(default="platform_user")
    display_name: str | None = None


class HrAssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=20000)
    context_id: str = Field(min_length=1, max_length=128)
    task_id: str | None = Field(default=None, min_length=1, max_length=128)
    execution_subject: ExecutionSubject | None = None
    # 允许的公共上下文：execution_subject 单独成字段，其余进 context。
    context: dict = Field(default_factory=dict)

    @field_validator("context")
    @classmethod
    def _validate_context(cls, value: dict) -> dict:
        if not isinstance(value, dict):
            raise ValueError("context必须是对象")
        unknown = set(value) - set(ALLOWED_CONTEXT_KEYS)
        if unknown:
            raise ValueError(f"未知的上下文键:{sorted(unknown)}")
        if contains_sensitive_data(value):
            raise ValueError("上下文包含禁止内容")
        return value

    def locale(self) -> str:
        return str(self.context.get("locale") or "zh-CN")

    def normalized_message(self) -> str:
        return self.message.strip()


def parse_public_request(payload: dict) -> HrAssistantRequest:
    """解析并校验公共请求；失败抛 PublicRequestError(contract_error)。"""
    try:
        request = HrAssistantRequest.model_validate(payload)
    except Exception as exc:
        raise PublicRequestError("contract_error") from exc
    if request.locale() not in SUPPORTED_LOCALES:
        raise PublicRequestError(
            "contract_error", "当前仅支持 zh-CN。"
        )
    if contains_sensitive_data(request.message):
        raise PublicRequestError("contract_error", "请求包含禁止内容。")
    return request
