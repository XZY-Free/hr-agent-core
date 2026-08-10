"""Consult A2A请求允许列表与结构化Artifact结果。"""

from typing import Literal

from a2a.types import Message, Part
from pydantic import BaseModel, ConfigDict, Field

from apps.consult_agent.a2a.card import AGENT_NAME, AGENT_VERSION
from packages.agent_runtime.a2a.artifact import structured_result_parts
from packages.agent_runtime.a2a.context import (
    A2ARequestContext,
    RequestContractError,
    parse_request,
)


ConsultStatus = Literal[
    "succeeded",
    "need_more_information",
    "not_found",
    "rejected",
    "temporarily_unavailable",
    "failed",
]

class ConsultA2ARequest(A2ARequestContext):
    """Consult业务请求复用通用A2A上下文。"""


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
    return parse_request(message, ConsultA2ARequest)


def result_parts(result: ConsultA2AResult) -> list[Part]:
    """用官方TextPart和DataPart承载同一Artifact的展示与结构结果。"""
    return structured_result_parts(result.answer, result.model_dump(mode="json"))
