"""可独立构建的Consult运行时与veADK事件适配。"""

import os
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

# veADK 1.1.0默认DEBUG会记录完整工具响应。独立服务在导入veADK前收紧为INFO；
# 部署方仍可显式设置更高等级，禁止以默认DEBUG运行真实Knowledge。
os.environ.setdefault("LOGGING_LEVEL", "INFO")

from google.genai import types
from veadk import Agent, Runner

from apps.consult_agent.a2a.contract import ConsultA2ARequest, ConsultA2AResult
from apps.consult_agent.agent import build_consult_agent
from apps.consult_agent.tools.parse_document import bind_document_context
from packages.agent_runtime.model_config import extra_config_for, model_for
from packages.agent_runtime.user_input import TurnOutput
from packages.hr_domain.documents.context import decode_document_context


APP_NAME = "hr-consult-agent"
logger = logging.getLogger(__name__)
_PERSONAL_DATA = re.compile(
    r"(?:我|我的|帮我|本人).{0,10}(?:余额|几天年假|医疗期|年假.{0,6}折算)"
)
_LEAVE_ACTION = re.compile(
    r"(?:我要|我想|帮我|今天|明天|后天).{0,10}(?:请|申请|办理).{0,8}假"
)
_NON_HR = re.compile(r"电脑|报修|网络故障|打印机|软件安装|IT支持", re.IGNORECASE)
_NOT_FOUND_WORDS = ("没有查到", "未查到", "没有找到", "暂时没有", "未找到")
_OUT_OF_SCOPE_WORDS = ("不属于人力", "不属于 HR", "非人力资源")


@dataclass
class ConsultTurn:
    answer: str
    input_question: str | None = None
    tool_names: list[str] = field(default_factory=list)
    knowledge_scope: str | None = None
    sources: list[dict] = field(default_factory=list)
    truncated: bool = False
    error_code: str | None = None
    calculation: dict | None = None


@dataclass(frozen=True)
class ConsultObservation:
    """不含问题正文、知识切片和身份数据的单次调用观测。"""

    request_id: str
    tool_names: tuple[str, ...]
    knowledge_scope: str | None
    status: str
    error_code: str | None
    elapsed_ms: float


class TurnRunner(Protocol):
    async def run(self, request: ConsultA2ARequest) -> ConsultTurn: ...


class VeADKConsultTurnRunner:
    """用同一个hr_consult_agent定义执行独立会话并收集非敏感工具证据。"""

    def __init__(self, agent: Agent):
        self.runner = Runner(agent=agent, app_name=APP_NAME, user_id="a2a-user")

    async def run(self, request: ConsultA2ARequest) -> ConsultTurn:
        await self.runner.short_term_memory.create_session(
            app_name=APP_NAME,
            user_id=request.user_id,
            session_id=request.session_id,
        )
        document_context = decode_document_context(request.context_summary)
        text = request.message
        if request.context_summary and document_context is None:
            text = f"咨询背景摘要：{request.context_summary}\n用户问题：{text}"
        message = types.Content(role="user", parts=[types.Part(text=text)])
        output = TurnOutput()
        tool_names: list[str] = []
        knowledge_scope = None
        sources: list[dict] = []
        truncated = False
        error_code = None
        calculation = None
        bound_document = document_context.model_dump() if document_context else None
        with bind_document_context(bound_document):
            async for event in self.runner.run_async(
                user_id=request.user_id,
                session_id=request.session_id,
                new_message=message,
            ):
                output.observe(event)
                if not event.content or not event.content.parts:
                    continue
                for part in event.content.parts:
                    function_call = getattr(part, "function_call", None)
                    if function_call and getattr(function_call, "name", None):
                        tool_names.append(function_call.name)
                        if function_call.name == "kb_search":
                            knowledge_scope = dict(function_call.args or {}).get("scope")
                        continue
                    function_response = getattr(part, "function_response", None)
                    if function_response and getattr(function_response, "name", None):
                        response = function_response.response
                        if isinstance(response, dict):
                            if response.get("success") is False:
                                error_code = response.get("error_type") or "tool_failed"
                            data = response.get("data")
                            if function_response.name == "kb_search" and isinstance(data, list):
                                sources = [
                                    {"source": row["source"], "score": row["score"]}
                                    for row in data
                                    if isinstance(row, dict)
                                    and isinstance(row.get("source"), str)
                                    and isinstance(row.get("score"), (int, float))
                                    and not isinstance(row.get("score"), bool)
                                ]
                            if function_response.name == "parse_document" and isinstance(data, dict):
                                truncated = bool(data.get("truncated"))
                            if function_response.name == "attendance_calculation" and isinstance(data, dict):
                                calculation = data
                        continue
        answer = output.answer
        if not answer:
            answer = "咨询服务暂时无法生成回答。"
        return ConsultTurn(
            answer=answer,
            input_question=output.input_question,
            tool_names=tool_names,
            knowledge_scope=knowledge_scope,
            sources=sources,
            truncated=truncated,
            error_code=error_code,
            calculation=calculation,
        )


class ConsultRuntime:
    """独立Consult职责过滤和业务状态映射。"""

    def __init__(
        self,
        *,
        turn_runner: TurnRunner,
        observer: Callable[[ConsultObservation], None] | None = None,
    ):
        self.turn_runner = turn_runner
        self.observer = observer

    async def run(self, request: ConsultA2ARequest) -> ConsultA2AResult:
        started = time.perf_counter()
        rejected = _rejection(request.message)
        if rejected:
            answer, category, error_code = rejected
            result = _result(
                request,
                status="rejected",
                answer=answer,
                category=category,
                error_code=error_code,
            )
            self._observe(request, result, (), started)
            return result

        turn = await self.turn_runner.run(request)
        category = _question_category(request.message, turn)
        status = "succeeded"
        error_code = turn.error_code
        if error_code and (
            error_code.startswith("knowledge_") or error_code == "kb_unavailable"
        ):
            status = "temporarily_unavailable"
        elif error_code == "need_more_information" and (
            "attendance_calculation" in turn.tool_names
        ):
            # 考勤计算缺月度豁免上下文 → need_more_information，不归为 failed。
            status = "need_more_information"
            error_code = None
        elif turn.input_question is not None:
            status = "need_more_information"
            error_code = None
        elif not turn.tool_names and any(
            word in turn.answer for word in _OUT_OF_SCOPE_WORDS
        ):
            status = "rejected"
            error_code = "out_of_scope"
        elif "kb_search" in turn.tool_names and (
            not turn.sources or any(word in turn.answer for word in _NOT_FOUND_WORDS)
        ):
            status = "not_found"
            error_code = "knowledge_not_found"
        elif error_code:
            status = "failed"
        result = _result(
            request,
            status=status,
            answer=turn.input_question if status == "need_more_information" else turn.answer,
            category=category,
            knowledge_scope=turn.knowledge_scope,
            sources=turn.sources,
            truncated=turn.truncated,
            recommend_hr=status in {"not_found", "temporarily_unavailable", "failed"},
            error_code=error_code,
            calculation=turn.calculation,
        )
        self._observe(request, result, tuple(turn.tool_names), started)
        return result

    def _observe(
        self,
        request: ConsultA2ARequest,
        result: ConsultA2AResult,
        tool_names: tuple[str, ...],
        started: float,
    ) -> None:
        observation = ConsultObservation(
            request_id=request.request_id,
            tool_names=tool_names,
            knowledge_scope=result.knowledge_scope,
            status=result.status,
            error_code=result.error_code,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
        if self.observer:
            self.observer(observation)
        logger.info(
            "consult_runtime_turn request_id=%s tools=%s scope=%s status=%s "
            "error_code=%s elapsed_ms=%.1f",
            observation.request_id,
            ",".join(observation.tool_names) or "none",
            observation.knowledge_scope or "none",
            observation.status,
            observation.error_code or "none",
            observation.elapsed_ms,
        )


def _rejection(message: str) -> tuple[str, str, str] | None:
    if _PERSONAL_DATA.search(message):
        return (
            "我只负责人力制度咨询，不能查询员工本人数据，请通过HR业务入口查询。",
            "personal_data",
            "personal_data_not_allowed",
        )
    if _LEAVE_ACTION.search(message):
        return (
            "我只负责人力制度咨询，不办理请假，请返回HR业务入口办理。",
            "leave_request",
            "leave_request_not_allowed",
        )
    if _NON_HR.search(message):
        return (
            "该问题不属于人力制度咨询范围，请联系对应支持部门。",
            "non_hr",
            "out_of_scope",
        )
    return None


def _question_category(message: str, turn: ConsultTurn) -> str:
    if "attendance_calculation" in turn.tool_names:
        return "attendance_calculation"
    if "parse_document" in turn.tool_names or re.search(r"https?://", message):
        return "hr_document"
    if "育儿假" in message:
        return "childcare_policy"
    return {
        "policy": "hr_policy",
        "handbook": "hr_system_operation",
        "salary": "hr_benefit",
        "childcare": "childcare_policy",
        "all": "hr_policy",
    }.get(turn.knowledge_scope, "hr_consultation")


def _result(
    request: ConsultA2ARequest,
    *,
    status: str,
    answer: str,
    category: str,
    knowledge_scope: str | None = None,
    sources: list[dict] | None = None,
    truncated: bool = False,
    recommend_hr: bool = False,
    error_code: str | None = None,
    calculation: dict | None = None,
) -> ConsultA2AResult:
    return ConsultA2AResult(
        request_id=request.request_id,
        status=status,
        answer=answer,
        question_category=category,
        knowledge_scope=knowledge_scope,
        sources=sources or [],
        truncated=truncated,
        recommend_hr=recommend_hr,
        error_code=error_code,
        calculation=calculation,
    )


def validate_standalone_config() -> None:
    """独立启动时对真实模型与Knowledge必要配置执行fail-closed检查。"""
    required = ["MODEL_AGENT_API_KEY"]
    if os.getenv("KB_BACKEND", "").strip() != "agentkit":
        raise RuntimeError("独立Consult要求KB_BACKEND=agentkit")
    required.extend([
        "VOLCENGINE_ACCESS_KEY",
        "VOLCENGINE_SECRET_KEY",
        "KB_COLLECTION_POLICY",
        "KB_COLLECTION_HANDBOOK",
        "KB_COLLECTION_SALARY",
        "KB_COLLECTION_CHILDCARE",
    ])
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError("独立Consult缺少必要服务端配置：" + ", ".join(missing))


def build_consult_runtime(
    *,
    validate_config: bool = True,
    observer: Callable[[ConsultObservation], None] | None = None,
) -> ConsultRuntime:
    if validate_config:
        validate_standalone_config()
    agent = build_consult_agent(
        model_name=model_for("consult"),
        model_extra_config=extra_config_for("consult"),
    )
    return ConsultRuntime(
        turn_runner=VeADKConsultTurnRunner(agent),
        observer=observer,
    )
