"""通用A2A请求上下文、metadata允许列表与敏感字段过滤。"""

import re
from typing import TypeVar

from a2a.types import Message, Role
from a2a.utils import get_message_text
from pydantic import BaseModel, ConfigDict, Field, ValidationError


_REQUEST_METADATA_FIELDS = {
    "request_id",
    "user_id",
    "session_id",
    "caller_agent",
    "locale",
    "context_summary",
}
_SENSITIVE_PATTERN = re.compile(
    r"client_secret|grant_type|authorization\s*:|bearer\s+|"
    r"volcengine_(?:access|secret)_key|model_agent_api_key|runtime_api_key|"
    r"gaia\s*_?jwt|\b(?:ak|sk)\s*[:=]|api[_ -]?key\s*[:=]|"
    r"employee\s*_?id|target_employee_id|corp_id",
    re.IGNORECASE,
)


class RequestContractError(ValueError):
    """不回显输入正文和字段值的A2A请求错误。"""


class A2ARequestContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    caller_agent: str = Field(pattern="^hr_orchestrator$")
    locale: str = Field(pattern="^zh-CN$")
    message: str = Field(min_length=1)
    context_summary: str


RequestModel = TypeVar("RequestModel", bound=A2ARequestContext)


def parse_request(message: Message | None, model: type[RequestModel]) -> RequestModel:
    """从官方Message提取严格通用上下文并执行敏感内容过滤。"""
    if message is None or message.role != Role.user:
        raise RequestContractError("A2A请求字段无效")
    metadata = message.metadata
    if not isinstance(metadata, dict) or set(metadata) != _REQUEST_METADATA_FIELDS:
        raise RequestContractError("A2A请求字段无效")
    text = get_message_text(message).strip()
    try:
        request = model.model_validate({**metadata, "message": text})
    except ValidationError:
        raise RequestContractError("A2A请求字段无效") from None
    if message.context_id and message.context_id != request.session_id:
        raise RequestContractError("A2A请求字段无效")
    if _SENSITIVE_PATTERN.search(request.message) or _SENSITIVE_PATTERN.search(
        request.context_summary
    ):
        raise RequestContractError("A2A请求包含禁止内容")
    return request


def contains_sensitive_data(value) -> bool:
    """递归检查响应结构中的敏感字段名或凭据标记。"""
    if isinstance(value, dict):
        return any(
            _SENSITIVE_PATTERN.search(str(key)) or contains_sensitive_data(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_sensitive_data(item) for item in value)
    return isinstance(value, str) and bool(_SENSITIVE_PATTERN.search(value))
