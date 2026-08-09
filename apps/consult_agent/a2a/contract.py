"""Consult A2A请求允许列表与结构化Artifact结果。"""

import re
from typing import Literal

from a2a.types import DataPart, Message, Part, Role, TextPart
from a2a.utils import get_message_text
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.consult_agent.a2a.card import AGENT_NAME, AGENT_VERSION


ConsultStatus = Literal[
    "succeeded",
    "need_more_information",
    "not_found",
    "rejected",
    "temporarily_unavailable",
    "failed",
]

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
    r"gaia\s*_?jwt|\b(?:ak|sk)\s*[:=]|api[_ -]?key\s*[:=]",
    re.IGNORECASE,
)


class RequestContractError(ValueError):
    """不回显输入内容的A2A请求错误。"""


class ConsultA2ARequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    caller_agent: Literal["hr_orchestrator"]
    locale: Literal["zh-CN"]
    message: str = Field(min_length=1)
    context_summary: str


class KnowledgeSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1)
    score: float


class ConsultA2AResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    status: ConsultStatus
    answer: str
    question_category: str
    knowledge_scope: str | None = None
    sources: list[KnowledgeSource] = Field(default_factory=list)
    truncated: bool = False
    recommend_hr: bool = False
    agent_name: Literal["hr-consult-agent"] = AGENT_NAME
    agent_version: Literal["1.0.0"] = AGENT_VERSION
    error_code: str | None = None


def parse_consult_request(message: Message | None) -> ConsultA2ARequest:
    """从官方Message的TextPart与metadata提取严格允许字段。"""
    if message is None or message.role != Role.user:
        raise RequestContractError("A2A请求字段无效")
    metadata = message.metadata
    if not isinstance(metadata, dict) or set(metadata) != _REQUEST_METADATA_FIELDS:
        raise RequestContractError("A2A请求字段无效")
    text = get_message_text(message).strip()
    raw = {**metadata, "message": text}
    try:
        request = ConsultA2ARequest.model_validate(raw)
    except ValidationError:
        raise RequestContractError("A2A请求字段无效") from None
    if message.context_id and message.context_id != request.session_id:
        raise RequestContractError("A2A请求字段无效")
    if _SENSITIVE_PATTERN.search(request.message) or _SENSITIVE_PATTERN.search(
        request.context_summary
    ):
        raise RequestContractError("A2A请求包含禁止内容")
    return request


def result_parts(result: ConsultA2AResult) -> list[Part]:
    """用官方TextPart和DataPart承载同一Artifact的展示与结构结果。"""
    return [
        Part(root=TextPart(text=result.answer)),
        Part(root=DataPart(data=result.model_dump(mode="json"))),
    ]
