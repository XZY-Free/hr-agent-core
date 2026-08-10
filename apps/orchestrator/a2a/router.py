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
    transport_mode,
)
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


class OrchestratorRemoteRouter:
    def __init__(
        self,
        *,
        consult_transport: str,
        employee_data_transport: str,
        client=None,
        route_table: DeterministicRouteTable | None = None,
        session_exists=None,
        consult_url: str = "http://127.0.0.1:8101",
        employee_data_url: str = "http://127.0.0.1:8102",
    ):
        self.consult_transport = transport_mode("HR_CONSULT_TRANSPORT", consult_transport)
        self.employee_data_transport = transport_mode(
            "HR_EMPLOYEE_DATA_TRANSPORT", employee_data_transport
        )
        self.client = client or OfficialA2AClient(
            timeout_seconds=float(os.getenv("HR_A2A_TIMEOUT_SECONDS", "30"))
        )
        self.route_table = route_table or DeterministicRouteTable()
        self.session_exists = session_exists
        self.consult_url = consult_url
        self.employee_data_url = employee_data_url

    async def route(self, payload: dict) -> RemoteRouteResponse | None:
        extracted = _extract_payload(payload)
        if extracted is None:
            return None
        user_id, session_id, message = extracted
        if self.session_exists is not None and not await self.session_exists(
            user_id=user_id, session_id=session_id
        ):
            return None
        target = self.route_table.decide(message, user_id=user_id, session_id=session_id)
        if target == RouteTarget.LOCAL:
            return None
        if target == RouteTarget.CONSULT and self.consult_transport == "local":
            return None
        if target == RouteTarget.EMPLOYEE_DATA and self.employee_data_transport == "local":
            return None

        request = A2ARequestContext(
            request_id=str(uuid4()),
            user_id=user_id,
            session_id=session_id,
            caller_agent="hr_orchestrator",
            locale="zh-CN",
            message=message,
            context_summary="",
        )
        spec = CONSULT_SPEC if target == RouteTarget.CONSULT else EMPLOYEE_SPEC
        base_url = self.consult_url if target == RouteTarget.CONSULT else self.employee_data_url
        started = time.perf_counter()
        try:
            invoked = await self.client.invoke(base_url=base_url, request=request, spec=spec)
            data = invoked.data
            if contains_sensitive_data(data):
                raise A2AInvocationError("a2a_security_error")
            if target == RouteTarget.CONSULT:
                answer, status = _validate_consult(data, request.request_id)
            else:
                answer, status = _validate_employee(data, request.request_id)
            self.route_table.record_remote_status(
                user_id=user_id,
                session_id=session_id,
                target=target,
                status=status,
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
    if status == "not_found":
        return "暂未查询到可靠制度，请联系HR或换个说法再问。", status
    if status in {"temporarily_unavailable", "failed"}:
        return "咨询服务暂时繁忙，请稍后重试。", status
    return data["answer"], status


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
        if query_type == "leave_balance":
            numbers = [data["leave_balance"]["remain"]]
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
    if not all(str(value) in answer for value in numbers):
        raise A2AInvocationError("a2a_contract_error")
