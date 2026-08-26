"""公共请求语义对象：SnowHarness → 企业人力智能助手 的唯一入口载荷。

不是内部 A2ARequestContext 的别名；禁止 employee_id / corp_id / 内部凭据。
context是严格schema对象，未知键与非法值一律contract_error，无fallback。
"""

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.agent_runtime.a2a.context import contains_sensitive_data
from apps.orchestrator.public_contract.invocation_context import (
    ALLOWED_CONTEXT_KEYS,
)

SUPPORTED_LOCALES = ("zh-CN",)

# 附件引用中禁止出现的内容形态：本地路径/凭据/原始内容。
_FORBIDDEN_ATTACHMENT_TOKENS = (
    "file://",
    "access_token",
    "secret",
    "raw_content",
)


class PublicRequestError(Exception):
    """公共请求校验失败，携带稳定机器错误码。"""

    def __init__(self, error_code: str, message: str = "公共请求不符合合同。"):
        super().__init__(message)
        self.error_code = error_code


class ExecutionSubject(BaseModel):
    """SnowHarness 本次执行所代表的可信调用者身份。

    只有两个字段且都显式：subject_id是平台侧opaque稳定主体，
    subject_kind只描述平台主体类型；不携带任何HR业务主键。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str = Field(min_length=1, max_length=128)
    subject_kind: Literal["platform_user", "platform_service"]


class AttachmentReference(BaseModel):
    """外部附件引用：只是公共引用，不是文件内容或凭据。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_id: str = Field(min_length=1, max_length=256)
    resource_type: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=256)
    media_type: str | None = Field(default=None, max_length=128)

    @field_validator("reference_id", "display_name")
    @classmethod
    def _reject_pathlike(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value.startswith(("/", "\\")) or "file://" in value or ".." in value:
            raise ValueError("附件引用禁止本地路径形态")
        return value


class PublicRequestContext(BaseModel):
    """调用上下文严格schema：只允许冻结合同键，非法值即错误。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    current_datetime: str | None = Field(
        default=None, min_length=1, max_length=64
    )
    locale: str | None = Field(default=None, min_length=1, max_length=16)
    conversation_summary: str | None = Field(
        default=None, min_length=1, max_length=20000
    )
    attachment_references: list[AttachmentReference] | None = None

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str | None):
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            raise ValueError(f"非法IANA时区:{value}") from None
        return value

    @field_validator("current_datetime")
    @classmethod
    def _validate_datetime(cls, value: str | None):
        if value is None:
            return value
        try:
            datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("current_datetime必须为ISO 8601格式") from None
        return value

    @field_validator("locale")
    @classmethod
    def _validate_locale(cls, value: str | None):
        if value is None:
            return value
        if value not in SUPPORTED_LOCALES:
            raise ValueError(f"locale只支持zh-CN，收到:{value}")
        return value

    @field_validator("conversation_summary")
    @classmethod
    def _validate_summary(cls, value: str | None):
        if value is None:
            return value
        lowered = value.lower()
        for token in _FORBIDDEN_ATTACHMENT_TOKENS:
            if token in lowered:
                raise ValueError("对话摘要包含禁止内容")
        return value

    @field_validator("attachment_references")
    @classmethod
    def _validate_attachments(cls, value):
        if value is None:
            return value
        serialized = value.__repr__().lower()
        for token in _FORBIDDEN_ATTACHMENT_TOKENS:
            if token in serialized:
                raise ValueError("附件引用包含禁止内容")
        return value


class HrAssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=20000)
    context_id: str = Field(min_length=1, max_length=128)
    task_id: str | None = Field(default=None, min_length=1, max_length=128)
    execution_subject: ExecutionSubject | None = None
    # 严格公共上下文：execution_subject单独成字段。
    context: PublicRequestContext = Field(default_factory=PublicRequestContext)

    def locale(self) -> str:
        return self.context.locale or "zh-CN"

    def normalized_message(self) -> str:
        return self.message.strip()


def parse_public_request(payload: dict) -> HrAssistantRequest:
    """解析并校验公共请求；失败抛 PublicRequestError(contract_error)。"""
    try:
        request = HrAssistantRequest.model_validate(payload)
    except Exception as exc:
        raise PublicRequestError("contract_error") from exc
    if contains_sensitive_data(request.message):
        raise PublicRequestError("contract_error", "请求包含禁止内容。")
    return request
