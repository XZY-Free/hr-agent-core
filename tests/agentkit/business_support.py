"""WP-01 公共身份远端验收：测试专用只读辅助。

范围：只做真实 HTTPS A2A 调用（三个 AgentKit 开发 Runtime）与只读身份判定。
绝不：import apps/packages/veadk、启动本地应用/模型/服务、伪造或本地 stub、
写云、打印凭据/主体/响应正文/身份映射/oracle 数值、把伪匿名 internal_user_id
当作业务 employee_id、把匿名/未映射当作成功业务结果、在服务不可用时伪装成通过。

安全：所有错误收敛成安全类别（不抛原异常消息/不回显响应体）。协议层对“非法参数”
只认 JSON-RPC -32602（a2a.client.errors.A2AClientJSONRPCError.error.code==-32602）；
HTTP 401/500、超时、JSON 解析、内部错误码一律视为失败 AcceptanceError，绝不当作
预期拒绝。期望的 employee_ref 与 medical_period 数值来自已发布 stub，由操作方 root
按现有 HMAC 规则经 HR_ACCEPTANCE_IDENTITY_ORACLE_JSON 注入；本文件绝不自行推断。
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx

from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError, A2AClientJSONRPCError
from a2a.types import DataPart, Message, Part, Role, Task, TaskIdParams, TextPart

from tests.agentkit import support

ORACLE_ENV = "HR_ACCEPTANCE_IDENTITY_ORACLE_JSON"

# 同一句词面：公共查询与 Employee 结构化查询共用，仅 task_id / 通道不同。
IDENTITY_MESSAGE = "我的医疗期余额"

USER_KIND = "platform_user"
SERVICE_KIND = "platform_service"
ERROR_IDENTITY_UNVERIFIED = "identity_unverified"
EMPLOYEE_DATA_RESULT_TYPE = "employee_data"

_HTTP_TIMEOUT_SECONDS = 90

# 安全错误类别（不携带原异常消息 / 响应体）。
_ERROR_MALFORMED = "远端响应缺少预期的结构化结果"
_ERROR_REJECT = "远端调用被协议/参数校验拒绝(-32602)"
_ERROR_RPC = "远端调用返回非预期协议错误"
_ERROR_NETWORK = "远端调用网络或服务不可用"
_ERROR_ENV = "远端验收环境未就绪"
_ERROR_CANCELED = "远端任务被成功取消(不应暴露公共cancel)"

# JSON-RPC Invalid params 标准码：只有它被视为“预期的参数非法拒绝”。
_INVALID_PARAMS = -32602
# A2A UnsupportedOperationError 标准码：公共任务拒绝 cancel 的唯一合法信号。
_CANCEL_UNSUPPORTED = -32004


class AcceptanceError(RuntimeError):
    """收敛后的接受性失败；不回显原始异常消息或响应正文。"""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


# --------------------------------------------------------------------------
# 敏感值通用断言：放在本模块里避免 pytest 断言内省打印主体/oracle/ref。
# --------------------------------------------------------------------------
def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def new_context() -> str:
    return f"wp01-{uuid4().hex}"


# --------------------------------------------------------------------------
# 公共主体 → 确定性 internal_user_id（与生产 derive_internal_user_id 一致）
# --------------------------------------------------------------------------
def derive_internal_user_id(subject_kind: str, subject_id: str) -> str:
    canonical = f"snowharness\0{subject_kind}\0{subject_id}".encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()[:32]
    return f"snowharness-{digest}"


# --------------------------------------------------------------------------
# 身份 oracle：只读加载 + 严格校验（两条主体、ref 唯一、medical 余额互异）。
# 缺失/不合法即失败，绝不 skip/xfail；校验发生在 fixture 装入期，而非独立测试。
# --------------------------------------------------------------------------
@dataclass(frozen=True, repr=False)
class OracleSubject:
    subject_id: str
    subject_kind: str
    employee_ref: str
    medical_period: dict[str, Any] = field(repr=False)


def load_identity_oracle() -> dict[str, OracleSubject]:
    raw = os.getenv(ORACLE_ENV, "")
    if not raw.strip():
        raise RuntimeError(f"缺少身份 oracle：请注入 {ORACLE_ENV}")
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError("身份 oracle 不是合法 JSON") from None
    if not isinstance(rows, list) or len(rows) < 2:
        raise RuntimeError("身份 oracle 要求至少两条已映射主体")
    subjects: dict[str, OracleSubject] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("身份 oracle 行必须是对象")
        subject_id = str(row.get("subject_id") or "").strip()
        employee_ref = str(row.get("employee_ref") or "").strip()
        kind = str(row.get("subject_kind") or USER_KIND).strip() or USER_KIND
        medical = row.get("medical_period")
        if not subject_id:
            raise RuntimeError("身份 oracle 行缺少 subject_id")
        if not employee_ref:
            raise RuntimeError("身份 oracle 行缺少 employee_ref")
        if kind not in (USER_KIND, SERVICE_KIND):
            raise RuntimeError("身份 oracle subject_kind 必须是 platform_user/platform_service")
        if not isinstance(medical, dict) or "balance" not in medical:
            raise RuntimeError("身份 oracle 行缺少 medical_period.balance")
        balance = medical.get("balance")
        if isinstance(balance, bool) or not isinstance(balance, (int, float)):
            raise RuntimeError("身份 oracle medical_period.balance 必须是数字")
        if subject_id in subjects:
            raise RuntimeError("身份 oracle 存在重复 subject_id")
        subjects[subject_id] = OracleSubject(
            subject_id=subject_id,
            subject_kind=kind,
            employee_ref=employee_ref,
            medical_period=dict(medical),
        )
    if len(subjects) < 2:
        raise RuntimeError("身份 oracle 要求至少两个不同的已映射主体")
    refs = [s.employee_ref for s in subjects.values()]
    if len(set(refs)) != len(refs):
        raise RuntimeError("身份 oracle 两个已映射主体 employee_ref 必须互异")
    balances = [s.medical_period["balance"] for s in subjects.values()]
    if len(set(balances)) != len(balances):
        raise RuntimeError("身份 oracle 两个已映射主体 medical_period.balance 必须互异")
    return subjects


# --------------------------------------------------------------------------
# 端点 / AgentCard 校验（避免向非公网地址或另一主机发送）
# --------------------------------------------------------------------------
def _normalize_url(url: str) -> str | None:
    parsed = urllib.parse.urlsplit(url or "")
    if not parsed.scheme or not parsed.netloc:
        return None
    path = (parsed.path or "/").rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _validate_endpoint(endpoint: str) -> None:
    issue = support.endpoint_issue(endpoint)
    if issue:
        raise AcceptanceError(f"{_ERROR_ENV}: 端点不合规 {issue}")


def _validate_card_url(endpoint: str, card) -> None:
    issue = support.endpoint_issue(card.url)
    if issue:
        raise AcceptanceError(f"{_ERROR_ENV}: AgentCard 公布地址不合规 {issue}")
    if _normalize_url(card.url) != _normalize_url(endpoint):
        raise AcceptanceError(f"{_ERROR_ENV}: AgentCard 公布地址与实际端点不一致")


# --------------------------------------------------------------------------
# A2A 消息构造
# --------------------------------------------------------------------------
def _message(text: str, *, context_id: str, task_id: str | None, metadata: dict) -> Message:
    return Message(
        role=Role.user,
        message_id=str(uuid4()),
        context_id=context_id,
        task_id=task_id,
        metadata=metadata,
        parts=[Part(root=TextPart(text=text))],
    )


def orchestrator_message(
    text: str,
    *,
    context_id: str | None = None,
    task_id: str | None = None,
    execution_subject: dict | None = None,
    extra_metadata: dict | None = None,
) -> Message:
    """公共 Orchestrator 消息；execution_subject 为 None 表示匿名。"""
    metadata: dict[str, Any] = {"locale": "zh-CN"}
    if execution_subject is not None:
        metadata["execution_subject"] = execution_subject
    if extra_metadata:
        metadata.update(extra_metadata)
    return _message(
        text,
        context_id=context_id or new_context(),
        task_id=task_id,
        metadata=metadata,
    )


def employee_message(
    text: str,
    *,
    session_id: str | None = None,
    internal_user_id: str,
    context_summary: str = "",
) -> Message:
    """Employee Data 结构化查询消息：走内部可信 A2A 契约（caller_agent=hr_orchestrator）。

    context_summary 仅向后兼容地携带附件/文档上下文；默认空串保持 WP-03/04 原有行为。
    """
    session_id = session_id or new_context()
    metadata = {
        "request_id": str(uuid4()),
        "user_id": internal_user_id,
        "session_id": session_id,
        "caller_agent": "hr_orchestrator",
        "locale": "zh-CN",
        "context_summary": context_summary,
    }
    return _message(text, context_id=session_id, task_id=None, metadata=metadata)


# --------------------------------------------------------------------------
# A2A 调用（Bearer access key + SDK 发现端点 + 卡校验）
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class A2AResponse:
    task: Task
    data: dict


@dataclass(frozen=True)
class ContinuationOutcome:
    response: A2AResponse | None
    rejected: bool          # True 仅当 -32602 预期参数非法拒绝
    category: str | None    # 其余失败的安全类别


def _target_endpoint_and_key(probes, target_key: str) -> tuple[str, str]:
    probe = probes[target_key]
    endpoint = probe.endpoint
    api_key = os.getenv(probe.api_key_env, "").strip()
    if not endpoint:
        raise AcceptanceError(f"{_ERROR_ENV}: 运行时端点未就绪")
    if not api_key:
        raise AcceptanceError(f"{_ERROR_ENV}: 缺少 acceptance key {probe.api_key_env}")
    _validate_endpoint(endpoint)
    return endpoint, api_key


async def _open_and_send(
    endpoint: str,
    api_key: str,
    message: Message,
    *,
    streaming: bool,
) -> Task:
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    events: list = []
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT_SECONDS,
            headers=headers,
            follow_redirects=False,
        ) as http:
            card = await A2ACardResolver(http, endpoint.rstrip("/")).get_agent_card()
            _validate_card_url(endpoint, card)
            client = ClientFactory(ClientConfig(
                streaming=streaming,
                httpx_client=http,
                supported_transports=["JSONRPC"],
            )).create(card)
            async for event in client.send_message(message):
                events.append(event)
    except A2AClientJSONRPCError as exc:
        if getattr(getattr(exc, "error", None), "code", None) == _INVALID_PARAMS:
            raise AcceptanceError(_ERROR_REJECT) from None
        raise AcceptanceError(_ERROR_RPC) from None
    except A2AClientError:
        raise AcceptanceError(_ERROR_RPC) from None
    except httpx.RequestError:
        raise AcceptanceError(_ERROR_NETWORK) from None
    task = _final_task(events)
    if task is None:
        raise AcceptanceError(_ERROR_MALFORMED)
    return task


def _final_task(events: list) -> Task | None:
    tasks = [ev[0] for ev in events if isinstance(ev, tuple) and ev]
    return tasks[-1] if tasks else None


def _extract_data(task: Task) -> dict:
    if not task.artifacts:
        raise AcceptanceError(_ERROR_MALFORMED)
    for part in task.artifacts[-1].parts:
        if isinstance(part.root, DataPart):
            return part.root.data
    raise AcceptanceError(_ERROR_MALFORMED)


async def request_full(
    probes,
    target_key: str,
    message: Message,
    *,
    streaming: bool = True,
) -> A2AResponse:
    """返回 (Task, 结构化 DataPart)；任何协议/网络/结构失败都收敛为 AcceptanceError。"""
    endpoint, api_key = _target_endpoint_and_key(probes, target_key)
    task = await _open_and_send(endpoint, api_key, message, streaming=streaming)
    return A2AResponse(task=task, data=_extract_data(task))


async def request_task(
    probes,
    target_key: str,
    message: Message,
    *,
    streaming: bool = True,
) -> dict:
    """只返回结构化 DataPart；供绝大多数断言场合使用。"""
    return (await request_full(probes, target_key, message, streaming=streaming)).data


async def request_continuation(
    probes,
    target_key: str,
    message: Message,
    *,
    streaming: bool = True,
) -> ContinuationOutcome:
    """发送一条续接/嵌套消息并区分：-32602 预期拒绝 / 结构化结果 / 其它失败。"""
    try:
        response = await request_full(probes, target_key, message, streaming=streaming)
        return ContinuationOutcome(response=response, rejected=False, category=None)
    except AcceptanceError as exc:
        return ContinuationOutcome(
            response=None,
            rejected=(exc.category == _ERROR_REJECT),
            category=exc.category,
        )


async def request_reject(
    probes,
    target_key: str,
    message: Message,
    *,
    streaming: bool = False,
) -> bool:
    """期望以 -32602 协议拒绝：命中即 True；意外成功、其它协议错误、网络错误均为 False。"""
    try:
        await request_task(probes, target_key, message, streaming=streaming)
        return False
    except AcceptanceError as exc:
        return exc.category == _ERROR_REJECT


# --------------------------------------------------------------------------
# WP-07 远端只读辅助：对既有任务调用官方 client.cancel_task，只认 A2A
# UnsupportedOperationError(-32004) 作为「公共任务拒绝取消」的唯一合法信号。
# 成功取消、-32002(TaskNotCancelable)、-32602、网络/鉴权/其它 RPC 错误一律失败。
# 绝不回显 task_id / 响应体 / 原异常消息。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class CancelOutcome:
    """去敏感 cancel 结果：unsupported 唯一表示服务端以 -32004 拒绝取消。"""

    unsupported: bool
    category: str | None


async def request_cancel(probes, target_key: str, task_id: str) -> CancelOutcome:
    """对既有任务调用官方 client.cancel_task；成功取消 / 非 -32004 均为失败。

    复用安全 endpoint/key helper（_target_endpoint_and_key）重新解析并校验同一张已部署
    AgentCard，经官方 A2A client 发送 tasks/cancel。任何协议/网络/鉴权失败与「成功取消」
    都收敛为 unsupported=False 的安全 category，绝不打印 task_id / 响应正文 / 异常消息。
    """
    endpoint, api_key = _target_endpoint_and_key(probes, target_key)
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT_SECONDS,
            headers=headers,
            follow_redirects=False,
        ) as http:
            card = await A2ACardResolver(http, endpoint.rstrip("/")).get_agent_card()
            _validate_card_url(endpoint, card)
            client = ClientFactory(ClientConfig(
                streaming=False,
                httpx_client=http,
                supported_transports=["JSONRPC"],
            )).create(card)
            await client.cancel_task(TaskIdParams(id=task_id))
    except A2AClientJSONRPCError as exc:
        code = getattr(getattr(exc, "error", None), "code", None)
        if code == _CANCEL_UNSUPPORTED:
            return CancelOutcome(unsupported=True, category=None)
        return CancelOutcome(unsupported=False, category=_ERROR_RPC)
    except A2AClientError:
        return CancelOutcome(unsupported=False, category=_ERROR_RPC)
    except httpx.RequestError:
        return CancelOutcome(unsupported=False, category=_ERROR_NETWORK)
    # 成功取消（无异常）＝ 暴露了公共 tasks/cancel，与不变量相反 -> 失败。
    return CancelOutcome(unsupported=False, category=_ERROR_CANCELED)


# --------------------------------------------------------------------------
# WP-02 远端只读辅助：读取公共结果里的唯一显式 LeaveDraft 快照与校验错误。
# 只认服务端结构化 data.load，绝不由 answer / 自然语言反推；未接线即断言失败。
# --------------------------------------------------------------------------
def public_data(data: dict, *, label: str = "公共") -> dict:
    """返回公共 result.data（dict）；数据体非 dict 视为未接线，归类为失败。"""
    inner = data.get("data")
    _check(isinstance(inner, dict), f"{label}公共结果未返回结构化 data 负载")
    return inner


def public_draft(data: dict, *, label: str = "公共") -> dict:
    """返回公共 result.data.draft 的唯一显式 LeaveDraft 快照。

    不是从 answer 解析，也不是自然语言推断；生产未接线时明确断言失败。
    """
    inner = public_data(data, label=label)
    draft = inner.get("draft")
    _check(isinstance(draft, dict), f"{label}公共结果未返回显式 Draft 快照(data.draft)")
    return draft
