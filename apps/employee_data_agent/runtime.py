"""Employee Data独立运行时：可信身份、职责过滤和确定性数字输出。"""

import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

os.environ.setdefault("LOGGING_LEVEL", "INFO")

from google.genai import types
from veadk import Agent, Runner

from apps.employee_data_agent.a2a.contract import (
    EmployeeDataA2ARequest,
    EmployeeDataA2AResult,
)
from apps.employee_data_agent.agent import build_employee_data_agent
from apps.employee_data_agent.identity import (
    IdentityResolutionError,
    TrustedIdentity,
    TrustedIdentityResolver,
)
from apps.employee_data_agent.provider import (
    EmployeeDataProvider,
    provider_from_env,
)
from apps.employee_data_agent.tools.query import bind_employee_request
from packages.agent_runtime.model_config import extra_config_for, model_for


APP_NAME = "hr-employee-data-agent"
logger = logging.getLogger(__name__)
_CROSS_EMPLOYEE = re.compile(
    r"(?:员工|同事|他|她|别人).{0,12}(?:编号|ID|工号|年假|医疗期|工龄)|EMP[-_]?\d+",
    re.IGNORECASE,
)
_LEAVE_ACTION = re.compile(r"(?:我要|我想|帮我|明天|后天).{0,10}(?:请|申请|办理).{0,8}假")
_POLICY = re.compile(r"制度|政策|规定|扣款|罚款|育儿假|餐补|系统.{0,4}(?:操作|怎么用)")


@dataclass
class EmployeeDataTurn:
    tool_name: str | None = None
    data: dict | None = None
    source: str | None = None
    partial: bool = False
    error_code: str | None = None


@dataclass(frozen=True)
class EmployeeDataObservation:
    request_id: str
    status: str
    query_type: str
    source: str | None
    tool_name: str
    partial: bool
    error_code: str | None
    elapsed_ms: float


class TurnRunner(Protocol):
    async def run(
        self,
        request: EmployeeDataA2ARequest,
        identity: TrustedIdentity,
        query_type: str,
    ) -> EmployeeDataTurn: ...


class VeADKEmployeeDataTurnRunner:
    def __init__(self, agent: Agent, provider: EmployeeDataProvider):
        self.runner = Runner(agent=agent, app_name=APP_NAME, user_id="employee-a2a-user")
        self.provider = provider

    async def run(self, request, identity, query_type) -> EmployeeDataTurn:
        await self.runner.short_term_memory.create_session(
            app_name=APP_NAME,
            user_id=request.user_id,
            session_id=request.session_id,
        )
        message = types.Content(role="user", parts=[types.Part(text=request.message)])
        turn = EmployeeDataTurn()
        with bind_employee_request(self.provider, identity.employee_id):
            async for event in self.runner.run_async(
                user_id=request.user_id,
                session_id=request.session_id,
                new_message=message,
            ):
                if not event.content or not event.content.parts:
                    continue
                for part in event.content.parts:
                    response = getattr(part, "function_response", None)
                    if not response or not getattr(response, "name", None):
                        continue
                    payload = response.response
                    if not isinstance(payload, dict):
                        return EmployeeDataTurn(
                            tool_name=response.name,
                            error_code="internal_data_error",
                        )
                    if payload.get("success") is False:
                        return EmployeeDataTurn(
                            tool_name=response.name,
                            source=payload.get("source"),
                            error_code=payload.get("error_type") or "internal_data_error",
                        )
                    turn = EmployeeDataTurn(
                        tool_name=response.name,
                        data=payload.get("data") if isinstance(payload.get("data"), dict) else {},
                        source=payload.get("source"),
                        partial=bool(payload.get("partial")),
                    )
        if not turn.tool_name:
            turn.error_code = "internal_data_error"
        return turn


class EmployeeDataRuntime:
    def __init__(
        self,
        *,
        identity_resolver: TrustedIdentityResolver,
        turn_runner: TurnRunner,
        clock: Callable[[], datetime] | None = None,
        observer: Callable[[EmployeeDataObservation], None] | None = None,
    ):
        self.identity_resolver = identity_resolver
        self.turn_runner = turn_runner
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.observer = observer

    async def run(self, request: EmployeeDataA2ARequest) -> EmployeeDataA2AResult:
        started = time.perf_counter()
        timestamp = self.clock().astimezone(timezone.utc).isoformat()
        rejected = _rejection(request.message)
        if rejected:
            result = self._result(
                request,
                data_as_of=timestamp,
                status="rejected",
                query_type="rejected",
                answer=rejected[0],
                error_code=rejected[1],
            )
            self._log(result, "none", started)
            return result
        query_type = _query_type(request.message)
        if query_type is None:
            result = self._result(
                request,
                data_as_of=timestamp,
                status="rejected",
                query_type="unsupported",
                answer="我只查询当前员工本人的假期余额、医疗期、工龄和年假折算。",
                error_code="policy_query_not_allowed",
            )
            self._log(result, "none", started)
            return result
        try:
            identity = self.identity_resolver.resolve(request.user_id)
        except IdentityResolutionError:
            result = self._result(
                request,
                data_as_of=timestamp,
                status="rejected",
                query_type=query_type,
                answer="当前身份无法完成本人数据查询。",
                error_code="identity_unverified",
            )
            self._log(result, "none", started)
            return result

        turn = await self.turn_runner.run(request, identity, query_type)
        if turn.error_code:
            status, retryable = _error_status(turn.error_code)
            result = self._result(
                request,
                data_as_of=timestamp,
                status=status,
                query_type=query_type,
                answer=_error_answer(turn.error_code),
                employee_ref=identity.employee_ref,
                source=turn.source,
                error_code=turn.error_code,
                retryable=retryable,
            )
            self._log(result, turn.tool_name or "none", started)
            return result

        selected, answer, selection_error = _select_data(query_type, turn.data or {})
        if selection_error:
            status, retryable = _error_status(selection_error)
            result = self._result(
                request,
                data_as_of=timestamp,
                status=status,
                query_type=query_type,
                answer=_error_answer(selection_error),
                employee_ref=identity.employee_ref,
                error_code=selection_error,
                retryable=retryable,
            )
        else:
            result = self._result(
                request,
                data_as_of=timestamp,
                status="succeeded",
                query_type=query_type,
                answer=answer,
                data=selected,
                source=turn.source,
                employee_ref=identity.employee_ref,
                partial=turn.partial,
                error_code="partial_data" if turn.partial else None,
            )
        self._log(result, turn.tool_name or "none", started)
        return result

    @staticmethod
    def _result(request, *, data_as_of: str, **kwargs) -> EmployeeDataA2AResult:
        return EmployeeDataA2AResult(
            request_id=request.request_id,
            data_as_of=data_as_of,
            **kwargs,
        )

    def _log(self, result, tool_name: str, started: float) -> None:
        observation = EmployeeDataObservation(
            request_id=result.request_id,
            status=result.status,
            query_type=result.query_type,
            source=result.source,
            tool_name=tool_name,
            partial=result.partial,
            error_code=result.error_code,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
        if self.observer:
            self.observer(observation)
        logger.info(
            "employee_data_turn request_id=%s status=%s query_type=%s source=%s "
            "tool=%s partial=%s error_code=%s elapsed_ms=%.1f",
            result.request_id,
            result.status,
            result.query_type,
            result.source or "none",
            tool_name,
            result.partial,
            result.error_code or "none",
            observation.elapsed_ms,
        )


def _rejection(message: str) -> tuple[str, str] | None:
    if _CROSS_EMPLOYEE.search(message):
        return "只能查询当前员工本人的数据，不能查询其他员工。", "cross_employee_query_not_allowed"
    if _LEAVE_ACTION.search(message):
        return "本人数据服务不办理请假，请返回人力助手办理。", "leave_request_not_allowed"
    if _POLICY.search(message):
        return "本人数据服务不解释制度，请使用人力制度咨询。", "policy_query_not_allowed"
    return None


def _query_type(message: str) -> str | None:
    if "医疗期" in message:
        return "medical_period"
    if any(word in message for word in ("折算", "档位", "年假怎么算")):
        return "annual_leave_calculation"
    if any(word in message for word in ("参工", "工龄", "入职多久")):
        return "employment_info"
    if "年假" in message or "年休假" in message or "假期余额" in message:
        return "leave_balance"
    return None


def _select_data(query_type: str, data: dict) -> tuple[dict | None, str, str | None]:
    if query_type == "medical_period":
        value = data.get("medical_period")
        if not isinstance(value, dict) or "balance" not in value:
            return None, "", "internal_data_error"
        return value, f"您的医疗期余额为{value['balance']}天。", None
    if query_type == "employment_info":
        value = data.get("employment")
        if not isinstance(value, dict) or "social_service_year" not in value:
            return None, "", "internal_data_error"
        years = value["social_service_year"]
        months = value.get("social_service_month", "0")
        days = value.get("social_service_day", "0")
        return value, f"您的参工年限为{years}年{months}个月{days}天。", None
    annual = data.get("annual_leave")
    if not isinstance(annual, dict):
        return None, "", "internal_data_error"
    if query_type == "leave_balance":
        balances = annual.get("balance")
        if not isinstance(balances, list) or not balances:
            return None, "", "employee_not_found"
        row = next((item for item in balances if item.get("leave_name") == "年休假"), balances[0])
        if "remain" not in row:
            return None, "", "internal_data_error"
        return {"leave_balance": row}, f"您的年休假余额为{row['remain']}天。", None
    if annual.get("mode") == "flat" and "quota" in annual:
        return data, f"您当前的年休假档位为{annual['quota']}天。", None
    if annual.get("mode") == "split" and {"before", "after"} <= set(annual):
        return data, (
            f"您今年跨年假档位，折算结果为跨档前{annual['before']}天、"
            f"跨档后{annual['after']}天。"
        ), None
    return None, "", "internal_data_error"


def _error_status(error_code: str) -> tuple[str, bool]:
    if error_code == "employee_not_found":
        return "not_found", False
    if error_code in {"gaia_auth_failed", "gaia_unavailable"}:
        return "temporarily_unavailable", True
    return "failed", False


def _error_answer(error_code: str) -> str:
    if error_code == "employee_not_found":
        return "没有查询到当前员工数据。"
    if error_code in {"gaia_auth_failed", "gaia_unavailable"}:
        return "本人数据暂时无法查询，请稍后重试。"
    return "本人数据查询失败，请稍后重试。"


def build_employee_data_runtime(
    *,
    identity_resolver: TrustedIdentityResolver | None = None,
    provider: EmployeeDataProvider | None = None,
) -> EmployeeDataRuntime:
    identity_resolver = identity_resolver or TrustedIdentityResolver.from_env()
    provider = provider or provider_from_env()
    agent = build_employee_data_agent(
        model_name=model_for("employee_data"),
        model_extra_config=extra_config_for("employee_data"),
    )
    return EmployeeDataRuntime(
        identity_resolver=identity_resolver,
        turn_runner=VeADKEmployeeDataTurnRunner(agent, provider),
    )
