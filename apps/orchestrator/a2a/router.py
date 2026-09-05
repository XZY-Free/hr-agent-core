"""Orchestrator远程调用、业务契约校验与固定失败行为。"""

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from uuid import uuid4

from apps.orchestrator.a2a.routing import (
    DeterministicRouteTable,
    RouteTarget,
)
from apps.orchestrator.a2a.semantic_router import Intent
from packages.agent_runtime.a2a.client import (
    A2AInvocationError,
    OfficialA2AClient,
    RemoteAgentSpec,
)
from packages.agent_runtime.a2a.context import (
    A2ARequestContext,
    contains_sensitive_data,
)


logger = logging.getLogger(__name__)
CONSULT_SPEC = RemoteAgentSpec(
    agent_name="hr-consult-agent",
    agent_version="1.0.0",
    allowed_statuses=frozenset({
        "succeeded", "need_more_information", "not_found", "rejected",
        "temporarily_unavailable", "failed",
    }),
    required_fields=frozenset({
        "request_id", "status", "answer", "question_category", "knowledge_scope",
        "sources", "truncated", "recommend_hr", "agent_name", "agent_version",
        "error_code",
    }),
)
EMPLOYEE_SPEC = RemoteAgentSpec(
    agent_name="hr-employee-data-agent",
    agent_version="1.0.0",
    allowed_statuses=frozenset({
        "succeeded", "not_found", "rejected", "temporarily_unavailable", "failed",
    }),
    required_fields=frozenset({
        "request_id", "status", "answer", "query_type", "data", "data_as_of",
        "source", "employee_ref", "partial", "agent_name", "agent_version",
        "error_code", "retryable",
    }),
)


@dataclass(frozen=True)
class RemoteRouteResponse:
    answer: str
    request_id: str
    target: str
    status: str
    error_code: str | None = None


@dataclass(frozen=True)
class RemoteContinuation:
    target: RouteTarget
    task_id: str
    context_id: str


@dataclass(frozen=True)
class LocalLeaveDispatch:
    """内部指令：semantic decision=leave_transaction 确定性派发本地 Leave runner。

    只由 OrchestratorRemoteRouter 产出，是路由指令而非公共远程状态；绝不能进入
    RemoteRouteResponse / _map_remote 或公共 result。Runtime 见它即走本地 Leave runner，
    并据此登记 local_leave continuation owner，而不是解析 answer / regex 推断。
    """


# 语义低置信度/歧义 → 固定、非敏感的本地澄清公共结果（经 Runtime 映射为
# input_required / missing_information，data 无 draft；含可接受澄清词）。
# target 必须是固定三值契约之一（local/consult/employee_data），故本地澄清用 "local"。
_LOCAL_CLARIFICATION_TARGET = "local"
LOCAL_CLARIFICATION_ANSWER = "为更好地帮您，请补充说明您是想办理请假、查询本人余额，还是了解哪项制度？"


class OrchestratorRemoteRouter:
    def __init__(
        self,
        *,
        client=None,
        route_table: DeterministicRouteTable | None = None,
        session_exists=None,
        context_summary_provider=None,
        consult_url: str = "http://127.0.0.1:8101",
        employee_data_url: str = "http://127.0.0.1:8102",
    ):
        self.client = client or OfficialA2AClient(
            timeout_seconds=float(os.getenv("HR_A2A_TIMEOUT_SECONDS", "30"))
        )
        self.route_table = route_table or DeterministicRouteTable()
        self.session_exists = session_exists
        self.context_summary_provider = context_summary_provider
        self.consult_url = consult_url
        self.employee_data_url = employee_data_url
        # 公共task按任务隔离；旧HTTP入口无task时按其user/session连续对话。
        self._continuations: dict[tuple[str, str, str | None], RemoteContinuation] = {}

    async def cancel_pending(self, *, user_id: str, session_id: str, task_id: str) -> None:
        key = (user_id, session_id, task_id)
        pending = self._continuations.get(key)
        if pending is None:
            return
        spec = CONSULT_SPEC if pending.target == RouteTarget.CONSULT else EMPLOYEE_SPEC
        base_url = self.consult_url if pending.target == RouteTarget.CONSULT else self.employee_data_url
        await self.client.cancel_task(base_url=base_url, spec=spec,
            task_id=pending.task_id, context_id=pending.context_id)
        self._continuations.pop(key, None)

    async def route(
        self, payload: dict, *, attachment_context_summary: str | None = None
    ) -> RemoteRouteResponse | LocalLeaveDispatch | None:
        extracted = _extract_payload(payload)
        if extracted is None:
            return None
        user_id, session_id, message = extracted
        if self.session_exists is not None and not await self.session_exists(
            user_id=user_id, session_id=session_id
        ):
            return None
        key = (user_id, session_id, payload.get("task_id"))
        pending = self._continuations.get(key)
        decision = None
        if pending:
            # continuation owner 优先（远程续接，不重分类）。
            target = pending.target
            clarification_required = False
        else:
            selection = await self.route_table.decide(
                message, user_id=user_id, session_id=session_id,
                task_id=payload.get("task_id"),
            )
            target = selection.target
            clarification_required = selection.clarification_required
            decision = selection.decision
        # 语义低置信度/歧义 → 固定本地澄清公共结果：不进入 Root/Leave，也不远程派发。
        # target 用三值契约的 "local"，绝不暴露非契约值。
        if clarification_required:
            return RemoteRouteResponse(
                answer=LOCAL_CLARIFICATION_ANSWER,
                request_id=str(uuid4()),
                target=_LOCAL_CLARIFICATION_TARGET,
                status="need_more_information",
            )
        if target == RouteTarget.LOCAL:
            # 普通 local（general_local / page/handoff/cancel/greeting guard）→ 仍进入 Root
            # （返回 None）；只有语义分类为 leave_transaction 时确定性派发本地 Leave runner，
            # 绝不依赖 answer 文本 / regex 推断。
            if decision is not None and decision.intent == Intent.LEAVE_TRANSACTION:
                return LocalLeaveDispatch()
            return None
        request_id = str(uuid4())
        context_summary = ""
        try:
            if target == RouteTarget.CONSULT:
                # 附件文档上下文优先（独立 DocumentContext 编码，不混入普通 summary）。
                if attachment_context_summary:
                    context_summary = attachment_context_summary
                elif self.context_summary_provider is not None:
                    context_summary = await self.context_summary_provider(
                        user_id=user_id,
                        session_id=session_id,
                        message=message,
                    )
                if not isinstance(context_summary, str) or contains_sensitive_data(
                    context_summary
                ):
                    raise A2AInvocationError("a2a_security_error")
        except A2AInvocationError as exc:
            return RemoteRouteResponse(
                answer="咨询服务暂时繁忙，请稍后重试。",
                request_id=request_id,
                target=CONSULT_SPEC.agent_name,
                status="failed",
                error_code=exc.error_code,
            )
        request = A2ARequestContext(
            request_id=request_id,
            user_id=user_id,
            session_id=session_id,
            caller_agent="hr_orchestrator",
            locale="zh-CN",
            message=message,
            context_summary=context_summary,
        )
        spec = CONSULT_SPEC if target == RouteTarget.CONSULT else EMPLOYEE_SPEC
        base_url = self.consult_url if target == RouteTarget.CONSULT else self.employee_data_url
        started = time.perf_counter()
        try:
            invoked = await self.client.invoke(base_url=base_url, request=request, spec=spec,
                **({"task_id": pending.task_id} if pending else {}))
            data = invoked.data
            if contains_sensitive_data(data):
                raise A2AInvocationError("a2a_security_error")
            if target == RouteTarget.CONSULT:
                answer, status = _validate_consult(data, request.request_id)
            else:
                answer, status = _validate_employee(data, request.request_id)
            if status == "need_more_information":
                self._continuations[key] = RemoteContinuation(target, invoked.task_id, invoked.context_id)
                # 同步 continuation owner（guard 优先：补充消息回到原 owner，不重分类）。
                self.route_table.record_remote_status(
                    user_id=user_id, session_id=session_id, target=target,
                    status=status, task_id=payload.get("task_id"),
                )
            else:
                self._continuations.pop(key, None)
                self.route_table.record_remote_status(
                    user_id=user_id, session_id=session_id, target=target,
                    status=status, task_id=payload.get("task_id"),
                )
            response = RemoteRouteResponse(
                answer=answer,
                request_id=request.request_id,
                target=spec.agent_name,
                status=status,
                error_code=data.get("error_code"),
            )
        except A2AInvocationError as exc:
            response = RemoteRouteResponse(
                answer=(
                    "咨询服务暂时繁忙，请稍后重试。"
                    if target == RouteTarget.CONSULT
                    else "本人数据暂时无法查询，请稍后重试。"
                ),
                request_id=request.request_id,
                target=spec.agent_name,
                status="failed",
                error_code=exc.error_code,
            )
        logger.info(
            "orchestrator_a2a request_id=%s session_ref=%s target=%s version=1.0.0 "
            "status=%s error_code=%s elapsed_ms=%.1f",
            response.request_id,
            hashlib.sha256(session_id.encode()).hexdigest()[:12],
            response.target,
            response.status,
            response.error_code or "none",
            (time.perf_counter() - started) * 1000,
        )
        return response


def _extract_payload(payload: dict) -> tuple[str, str, str] | None:
    user_id = payload.get("user_id")
    session_id = payload.get("session_id")
    message = payload.get("new_message")
    if not isinstance(user_id, str) or not user_id or not isinstance(session_id, str) or not session_id:
        return None
    if not isinstance(message, dict):
        return None
    parts = message.get("parts")
    if not isinstance(parts, list):
        return None
    texts = [part.get("text") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
    text = "\n".join(texts).strip()
    return (user_id, session_id, text) if text else None


def _base_validate(data: dict, request_id: str, spec: RemoteAgentSpec) -> None:
    if not spec.required_fields <= set(data):
        raise A2AInvocationError("a2a_contract_error")
    if data.get("agent_name") != spec.agent_name or data.get("agent_version") != spec.agent_version:
        raise A2AInvocationError("a2a_contract_error")
    if data.get("request_id") != request_id or data.get("status") not in spec.allowed_statuses:
        raise A2AInvocationError("a2a_contract_error")
    if not isinstance(data.get("answer"), str):
        raise A2AInvocationError("a2a_contract_error")


def _validate_consult(data: dict, request_id: str) -> tuple[str, str]:
    _base_validate(data, request_id, CONSULT_SPEC)
    status = data["status"]
    if status == "succeeded":
        sources = data.get("sources")
        if not isinstance(sources, list) or not all(
            isinstance(row, dict)
            and isinstance(row.get("source"), str)
            and isinstance(row.get("score"), (int, float))
            and not isinstance(row.get("score"), bool)
            for row in sources
        ):
            raise A2AInvocationError("a2a_contract_error")
        if data.get("knowledge_scope") is not None and not sources:
            raise A2AInvocationError("a2a_contract_error")
        if data.get("question_category") == "attendance_calculation":
            _validate_consult_calculation(data)
    if status == "not_found":
        return "暂未查询到可靠制度，请联系HR或换个说法再问。", status
    if status in {"temporarily_unavailable", "failed"}:
        return "咨询服务暂时繁忙，请稍后重试。", status
    return data["answer"], status


def _validate_consult_calculation(data: dict) -> None:
    """attendance_calculation 结果必须带计算证据且数字与 answer 一致。"""
    calc = data.get("calculation")
    if not isinstance(calc, dict):
        raise A2AInvocationError("a2a_contract_error")
    answer = data.get("answer", "")
    total_deduction = calc.get("total_deduction")
    total_absence_days = calc.get("total_absence_days")
    if not isinstance(total_deduction, (int, float)) or isinstance(total_deduction, bool):
        raise A2AInvocationError("a2a_contract_error")
    if not isinstance(total_absence_days, (int, float)) or isinstance(total_absence_days, bool):
        raise A2AInvocationError("a2a_contract_error")
    # answer 必须包含计算得出的金额与旷工天数（允许 0 值以"0"或"无"形式出现）。
    deduction_text = str(total_deduction)
    if total_deduction and deduction_text not in answer:
        raise A2AInvocationError("a2a_contract_error")
    if total_absence_days and str(total_absence_days) not in answer:
        raise A2AInvocationError("a2a_contract_error")
    if not isinstance(calc.get("records"), list):
        raise A2AInvocationError("a2a_contract_error")


def _validate_employee(data: dict, request_id: str) -> tuple[str, str]:
    _base_validate(data, request_id, EMPLOYEE_SPEC)
    status = data["status"]
    if status == "succeeded":
        if not isinstance(data.get("data"), dict) or not isinstance(data.get("source"), str):
            raise A2AInvocationError("a2a_contract_error")
        _validate_employee_numbers(data)
    if data.get("error_code") == "identity_unverified":
        return "当前身份无法完成本人数据查询。", status
    if status in {"temporarily_unavailable", "failed"}:
        return "本人数据暂时无法查询，请稍后重试。", status
    return data["answer"], status


def _validate_employee_numbers(result: dict) -> None:
    data = result["data"]
    query_type = result.get("query_type")
    answer = result["answer"]
    numbers = []
    try:
        if query_type == "leave_balance_by_type":
            row = data["leave_balance"]
            numbers = [row["remain"]]
            numbers.append(_unit_label(row.get("unit")))
        elif query_type == "leave_balance_all":
            rows = data["leave_balances"]
            if not isinstance(rows, list) or not rows:
                raise KeyError
            for row in rows:
                numbers.append(row["remain"])
        elif query_type == "medical_period":
            numbers = [data["balance"]]
        elif query_type == "employment_info":
            numbers = [data["social_service_year"]]
        elif query_type == "annual_leave_calculation":
            annual = data["annual_leave"]
            numbers = ([annual["quota"]] if annual.get("mode") == "flat"
                       else [annual["before"], annual["after"]])
        else:
            raise KeyError
    except (KeyError, TypeError):
        raise A2AInvocationError("a2a_contract_error") from None
    if not all(_serial(value) in answer for value in numbers):
        raise A2AInvocationError("a2a_contract_error")


def _serial(value) -> str:
    return str(value)


def _unit_label(unit: str | None) -> str:
    return "小时" if (unit or "day") == "hour" else "天"
