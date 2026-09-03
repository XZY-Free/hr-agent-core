"""批次2：公共执行门面单元测试（假依赖，不触发真实模型）。"""

import pytest

from apps.orchestrator.a2a.router import RemoteRouteResponse
from apps.orchestrator.public_runtime.identity_adapter import (
    ANONYMOUS_USER_ID,
    PublicIdentityAdapter,
)
from apps.orchestrator.public_runtime.request import (
    ExecutionSubject,
    parse_public_request,
    PublicRequestError,
)
from apps.orchestrator.public_runtime.runtime import HrAssistantRuntime
from packages.agent_runtime.user_input import TurnOutput


class FakeRemoteRouter:
    def __init__(self, response=None):
        self.response = response
        self.calls = []
        self.attachment_summaries = []

    async def route(self, payload, *, attachment_context_summary=None):
        self.calls.append(payload)
        self.attachment_summaries.append(attachment_context_summary)
        return self.response


class FakeRunner:
    def __init__(self, answer="好的", error=None, input_question=None):
        self.answer = answer
        self.input_question = input_question
        self.error = error
        self.calls = []

    async def run(self, *, messages, user_id, session_id):
        self.calls.append(
            {"messages": messages, "user_id": user_id, "session_id": session_id}
        )
        if self.error:
            raise self.error
        return TurnOutput(answer=self.answer, input_question=self.input_question)


def _payload(**overrides) -> dict:
    payload = {
        "request_id": "req-1",
        "message": "我的年假余额还有多少？",
        "context_id": "ctx-1",
        "context": {"locale": "zh-CN"},
    }
    payload.update(overrides)
    return payload


def _supported_attachment_resolver():
    from apps.orchestrator.public_runtime.attachments import (
        AccessMode,
        AttachmentResolver,
        ResolvedAttachment,
    )

    def _resolve(ref):
        return ResolvedAttachment(
            canonical_reference=ref.reference_id,
            resource_type=ref.resource_type,
            media_type=ref.media_type,
            display_name=ref.display_name,
            access_mode=AccessMode.TEXT,
            text="请假制度正文内容",
        )

    return AttachmentResolver(resolvers={"document": _resolve, "web_document": _resolve})


@pytest.mark.asyncio
async def test_remote_employee_data_maps_to_public_result():
    router = FakeRemoteRouter(
        RemoteRouteResponse(
            answer="您剩余年假 5 天。",
            request_id="inner-1",
            target="hr-employee-data-agent",
            status="succeeded",
        )
    )
    runtime = HrAssistantRuntime(
        remote_router=router, local_runner=FakeRunner()
    )
    result = await runtime.invoke(_payload())

    assert result.status == "completed"
    assert result.result_type == "employee_data"
    assert result.agent_name == "hr-assistant"
    assert result.agent_version == "1.0.0"
    assert result.request_id == "req-1"
    assert result.actions == []
    # 内部子智能体名称不得进入公共结果。
    assert "hr-employee-data-agent" not in result.to_payload().__str__()


@pytest.mark.asyncio
async def test_remote_need_more_information_maps_to_input_required():
    router = FakeRemoteRouter(
        RemoteRouteResponse(
            answer="请问您想咨询哪方面的制度？",
            request_id="inner-2",
            target="hr-consult-agent",
            status="need_more_information",
        )
    )
    runtime = HrAssistantRuntime(
        remote_router=router, local_runner=FakeRunner()
    )
    result = await runtime.invoke(_payload())

    assert result.status == "input_required"
    assert result.error_code == "input_required"
    assert result.result_type == "missing_information"


@pytest.mark.asyncio
async def test_local_path_injects_execution_context_header():
    runner = FakeRunner(answer="已为您打开我的表单。")
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=runner
    )
    result = await runtime.invoke(_payload(message="打开我的表单"))

    assert result.status == "completed"
    assert result.result_type == "conversation"
    call = runner.calls[0]
    assert call["messages"].startswith("【执行上下文】当前日期时间：")
    assert "打开我的表单" in call["messages"]
    assert call["session_id"] == "ctx-1"


@pytest.mark.asyncio
async def test_current_datetime_from_caller_context_is_preferred():
    runner = FakeRunner()
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=runner
    )
    await runtime.invoke(
        _payload(context={"current_datetime": "2026-01-02T09:00:00"})
    )
    assert "2026-01-02T09:00:00" in runner.calls[0]["messages"]


@pytest.mark.asyncio
async def test_local_runner_error_maps_to_stable_failed():
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None),
        local_runner=FakeRunner(error=RuntimeError("boom")),
    )
    result = await runtime.invoke(_payload())

    assert result.status == "failed"
    assert result.error_code == "failed"
    assert result.retryable is True
    assert "boom" not in result.answer


@pytest.mark.asyncio
async def test_invalid_contract_returns_contract_error():
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=FakeRunner()
    )
    result = await runtime.invoke({"request_id": "req-x", "message": ""})

    assert result.status == "failed"
    assert result.error_code == "contract_error"
    assert result.retryable is False


@pytest.mark.asyncio
async def test_unknown_context_key_rejected():
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=FakeRunner()
    )
    result = await runtime.invoke(
        _payload(context={"annual_leave": {"employee_id": "x"}})
    )

    assert result.error_code == "contract_error"


@pytest.mark.asyncio
async def test_employee_id_in_message_rejected():
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=FakeRunner()
    )
    result = await runtime.invoke(
        _payload(message="我的employee_id是12345，帮我查余额")
    )

    assert result.error_code == "contract_error"


def test_identity_adapter_namespacing():
    adapter = PublicIdentityAdapter()
    subject = ExecutionSubject(
        subject_id="snow-user-1", subject_kind="platform_user"
    )
    internal = adapter.internal_user_id(subject)
    assert internal.startswith("snowharness-")
    assert "snow-user-1" not in internal
    # 同一平台主体稳定映射；不同主体不冲突。
    assert internal == adapter.internal_user_id(subject)
    assert internal != adapter.internal_user_id(
        ExecutionSubject(
            subject_id="snow-user-2", subject_kind="platform_user"
        )
    )
    # user/service 同id不同hash。
    assert internal != adapter.internal_user_id(
        ExecutionSubject(
            subject_id="snow-user-1", subject_kind="platform_service"
        )
    )
    assert adapter.internal_user_id(None) == ANONYMOUS_USER_ID


def test_identity_adapter_fixed_algorithm():
    """固定算法：operator可离线用同一公式复算internal_user_id。"""
    import hashlib

    canonical = "snowharness\0platform_user\0snow-user-1"
    expected = "snowharness-" + hashlib.sha256(canonical.encode()).hexdigest()[:32]
    adapter = PublicIdentityAdapter()
    assert adapter.internal_user_id(
        ExecutionSubject(
            subject_id="snow-user-1", subject_kind="platform_user"
        )
    ) == expected


@pytest.mark.asyncio
async def test_execution_subject_flows_as_internal_user_id():
    router = FakeRemoteRouter(None)
    runner = FakeRunner()
    runtime = HrAssistantRuntime(remote_router=router, local_runner=runner)
    await runtime.invoke(
        _payload(
            execution_subject={
                "subject_id": "snow-user-1",
                "subject_kind": "platform_user",
            }
        )
    )
    assert router.calls[0]["user_id"].startswith("snowharness-")
    assert runner.calls[0]["user_id"].startswith("snowharness-")


@pytest.mark.asyncio
async def test_resume_without_subject_does_not_inherit_identity():
    """Resume缺subject时按本次请求处理：退化为匿名，不从旧任务偷身份。"""
    router = ScriptedRouter([None, None])
    runner = FakeRunner(answer="好的。")
    runtime = HrAssistantRuntime(remote_router=router, local_runner=runner)

    await runtime.invoke(
        _payload(
            message="我想请假",
            task_id="task-1",
            execution_subject={
                "subject_id": "snow-user-1",
                "subject_kind": "platform_user",
            },
        )
    )
    await runtime.invoke(
        _payload(request_id="req-2", message="年休假，明天一天", task_id="task-1")
    )
    assert router.calls[0]["user_id"].startswith("snowharness-")
    assert router.calls[1]["user_id"] == ANONYMOUS_USER_ID


@pytest.mark.asyncio
async def test_resume_same_subject_identity_continuity():
    """Resume重发同一subject时，两次执行内部身份一致。"""
    router = ScriptedRouter([None, None])
    runner = FakeRunner(answer="好的。")
    runtime = HrAssistantRuntime(remote_router=router, local_runner=runner)
    subject = {
        "subject_id": "snow-user-1",
        "subject_kind": "platform_user",
    }
    await runtime.invoke(
        _payload(message="我想请假", task_id="task-1", execution_subject=subject)
    )
    await runtime.invoke(
        _payload(
            request_id="req-2",
            message="年休假，明天一天",
            task_id="task-1",
            execution_subject=subject,
        )
    )
    assert router.calls[0]["user_id"] == router.calls[1]["user_id"]
    assert router.calls[0]["user_id"].startswith("snowharness-")


@pytest.mark.asyncio
async def test_subject_schema_strictness():
    """subject_kind必填枚举；display_name/employee_id等一律contract_error。"""
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=FakeRunner()
    )
    for bad_subject in (
        {"subject_id": "s1"},  # 缺subject_kind
        {"subject_id": "s1", "subject_kind": "employee"},  # 非法kind
        {"subject_id": "s1", "display_name": "张三"},  # 已删除字段
        {"subject_id": "s1", "subject_kind": "platform_user", "employee_id": "E1"},
        "snow-user-1",  # JSON string subject
    ):
        result = await runtime.invoke(_payload(execution_subject=bad_subject))
        assert result.error_code == "contract_error", bad_subject


def test_parse_public_request_rejects_corp_id_context():
    with pytest.raises(PublicRequestError):
        parse_public_request(_payload(context={"corp_id": "corp-1"}))


@pytest.mark.asyncio
async def test_local_path_binds_hr_execution_context_when_builder_configured():
    """装配 hr_context_builder 时，本地链在 request-scoped HR context 下运行。"""
    from packages.hr_domain.execution.context import current_hr_context

    observed = {}
    runner = FakeRunner(answer="好的。")
    original_run = runner.run

    async def _run(**kwargs):
        observed["context"] = current_hr_context()
        return await original_run(**kwargs)

    runner.run = _run
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None),
        local_runner=runner,
        hr_context_builder=lambda *, internal_user_id, request_id, context_id: (
            type("Ctx", (), {
                "internal_user_id": internal_user_id,
                "request_id": request_id,
                "context_id": context_id,
            })()
        ),
    )
    await runtime.invoke(
        _payload(
            message="我的年假余额还有多少？",
            execution_subject={
                "subject_id": "snow-user-1",
                "subject_kind": "platform_user",
            },
        )
    )

    assert observed["context"] is not None
    assert observed["context"].internal_user_id.startswith("snowharness-")
    assert observed["context"].request_id == "req-1"
    assert observed["context"].context_id == "ctx-1"


@pytest.mark.asyncio
async def test_local_path_without_builder_has_no_hr_context():
    """未装配 builder 时（如仅远程/问候）本地链下 HR context 为空，不因问候失败。"""
    from packages.hr_domain.execution.context import current_hr_context

    observed = {}
    runner = FakeRunner(answer="好的。")
    original_run = runner.run

    async def _run(**kwargs):
        observed["context"] = current_hr_context()
        return await original_run(**kwargs)

    runner.run = _run
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=runner
    )
    await runtime.invoke(_payload(message="你好"))
    assert observed["context"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer,is_missing",
    [
        ("好的，请问假期类型和日期分别是什么？", True),
        ("请问您想请哪种假？从哪天开始？", True),
        ("你想请年假的话，还需要告诉我开始日期以及请假时长或结束日期哦。", True),
        ("请补充开始日期和请假时长。", True),
        ("请问您想申请什么类型的假期", True),
        ("已整理好申请信息，请确认后再提交。", True),
        ("请假申请需要填写日期和时长。", False),
        ("开始日期为明天，时长一天，申请已提交。", False),
        ("你好！我是你的人力AI助手，可以帮你处理请假申请、查询假期余额、打开考勤相关页面等事务，有需要随时告诉我哦～", False),
        ("我能查询假期余额，有需要请告诉我。", False),
        ("请假需要填写日期和事由。如需其他帮助，请告诉我。", False),
        ("请问您想申请什么类型的假期？另外还需要您提供请假的开始日期、时长或结束日期，以及请假事由。", True),
        ("申请已提交：年休假 2026-08-26 全天 1 天。", False),
        ("已为您打开我的表单。", False),
    ],
)
async def test_local_explicit_input_request_maps_to_input_required(answer, is_missing):
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=FakeRunner(
            answer=answer, input_question=answer if is_missing else None,
        )
    )
    result = await runtime.invoke(_payload(message="帮我请假"))
    assert (result.status == "input_required") is is_missing
    if is_missing:
        assert result.error_code == "input_required"
    assert result.answer == answer


@pytest.mark.asyncio
async def test_question_text_alone_cannot_force_input_required():
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None),
        local_runner=FakeRunner(answer="申请时请告诉我日期？确认后提交。"),
    )
    assert (await runtime.invoke(_payload(message="你好"))).status == "completed"


@pytest.mark.asyncio
async def test_explicit_input_request_without_keywords_is_preserved():
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None),
        local_runner=FakeRunner(input_question="您的诉求是"),
    )
    result = await runtime.invoke(_payload())
    assert result.status == "input_required"
    assert result.answer == "您的诉求是"


class ScriptedRunner:
    """按调用顺序返回预设答案的本地 Runner 观察点。"""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def run(self, *, messages, user_id, session_id):
        self.calls.append(
            {"messages": messages, "user_id": user_id, "session_id": session_id}
        )
        answer = self.answers[len(self.calls) - 1]
        return answer if isinstance(answer, TurnOutput) else TurnOutput(answer=answer)


class ScriptedRouter:
    """按调用顺序返回预设响应的远程路由观察点；None 表示转本地。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def route(self, payload, *, attachment_context_summary=None):
        self.calls.append(payload)
        if len(self.calls) > len(self.responses):
            # 超出脚本次数的调用是生产缺陷导致的额外路由，回落 None 转本地，
            # 让路由计数断言以正确原因失败，而不是 IndexError 噪音。
            return None
        return self.responses[len(self.calls) - 1]


_MISSING = TurnOutput(input_question="好的，请问假期类型和日期分别是什么？")


def _consult_response(answer="这是咨询答复。"):
    return RemoteRouteResponse(
        answer=answer,
        request_id="inner-c",
        target="hr-consult-agent",
        status="succeeded",
    )


@pytest.mark.asyncio
async def test_pending_local_task_resume_bypasses_remote_routing():
    """同一 (context_id, task_id) 本地 input_required 后，补充消息不得再被远程路由改判。"""
    router = ScriptedRouter([None, _consult_response()])
    runner = ScriptedRunner([_MISSING, "好的，已记录您的补充信息。"])
    runtime = HrAssistantRuntime(remote_router=router, local_runner=runner)

    first = await runtime.invoke(
        _payload(message="我想请假", task_id="task-1")
    )
    assert first.status == "input_required"

    second = await runtime.invoke(
        _payload(
            request_id="req-2",
            message="年休假，明天一天",
            task_id="task-1",
        )
    )

    # 关键断言：续聊不得再次调用远程路由（当前实现会调用，RED）。
    assert len(router.calls) == 1
    # 续聊必须进入同一个本地 Runner / 会话。
    assert len(runner.calls) == 2
    assert runner.calls[0]["session_id"] == runner.calls[1]["session_id"] == "ctx-1"
    assert "年休假，明天一天" in runner.calls[1]["messages"]
    # 本切片只到安全的提交前状态，不允许出现提交性结果。
    assert second.status in ("input_required", "completed")
    assert "提交" not in second.answer


@pytest.mark.asyncio
async def test_pending_task_does_not_hijack_other_task_in_same_context():
    """同 context 下另一 task 必须走正常远程路由，不被本地挂起态劫持。"""
    router = ScriptedRouter([None, _consult_response()])
    runner = ScriptedRunner([_MISSING, "不应到达本地链"])
    runtime = HrAssistantRuntime(remote_router=router, local_runner=runner)

    await runtime.invoke(_payload(message="我想请假", task_id="task-1"))
    other = await runtime.invoke(
        _payload(request_id="req-2", message="公司年假制度是怎样的？", task_id="task-2")
    )

    assert len(router.calls) == 2
    assert len(runner.calls) == 1
    assert other.status == "completed"
    assert other.result_type == "consultation"


@pytest.mark.asyncio
async def test_request_without_task_id_does_not_inherit_pending():
    """task_id 缺失的请求不得继承挂起的本地续聊。"""
    router = ScriptedRouter([None, _consult_response()])
    runner = ScriptedRunner([_MISSING, "不应到达本地链"])
    runtime = HrAssistantRuntime(remote_router=router, local_runner=runner)

    await runtime.invoke(_payload(message="我想请假", task_id="task-1"))
    result = await runtime.invoke(
        _payload(request_id="req-2", message="公司年假制度是怎样的？")
    )

    assert len(router.calls) == 2
    assert len(runner.calls) == 1
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_pending_mark_clears_after_terminal_local_result():
    """本地续聊到达终态后，同一对的后续消息恢复正常路由。"""
    router = ScriptedRouter([None, _consult_response()])
    runner = ScriptedRunner([_MISSING, "已取消本次请假办理。"])
    runtime = HrAssistantRuntime(remote_router=router, local_runner=runner)

    await runtime.invoke(_payload(message="我想请假", task_id="task-1"))
    second = await runtime.invoke(
        _payload(request_id="req-2", message="年休假，明天一天", task_id="task-1")
    )
    assert second.status == "completed"
    third = await runtime.invoke(
        _payload(request_id="req-3", message="顺便问下制度", task_id="task-1")
    )

    # 第一次正常路由 + 终态清除后的第三次正常路由 = 2 次远程路由；
    # 续聊那次必须绕过路由直达本地，因此本地 Runner 恰好被调用 2 次。
    assert len(router.calls) == 2
    assert len(runner.calls) == 2
    assert third.result_type == "consultation"


class FlakyRunner:
    """第一次返回追问，第二次抛异常的本地 Runner。"""

    def __init__(self):
        self.calls = []

    async def run(self, *, messages, user_id, session_id):
        self.calls.append(session_id)
        if len(self.calls) > 1:
            raise RuntimeError("boom")
        return _MISSING


@pytest.mark.asyncio
async def test_pending_mark_clears_after_local_runner_error():
    """续聊本地 Runner 异常时挂起标记清除，重试恢复正常路由。"""
    router = ScriptedRouter([None, _consult_response()])
    runner = FlakyRunner()
    runtime = HrAssistantRuntime(remote_router=router, local_runner=runner)

    first = await runtime.invoke(_payload(message="我想请假", task_id="task-a"))
    assert first.status == "input_required"
    retry = await runtime.invoke(
        _payload(request_id="req-2", message="年休假，明天一天", task_id="task-a")
    )
    assert retry.status == "failed"
    assert retry.retryable is True

    normal = await runtime.invoke(
        _payload(request_id="req-3", message="换个话题", task_id="task-a")
    )
    # 第一次正常路由 + 终态(失败)清除后的第三次正常路由 = 2 次远程路由。
    assert len(router.calls) == 2
    assert normal.result_type == "consultation"


@pytest.mark.asyncio
async def test_resume_same_context_shares_session():
    runner = FakeRunner(answer="好的。")
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=runner
    )
    await runtime.invoke(_payload())
    await runtime.invoke(_payload(request_id="req-2", message="继续"))
    assert runner.calls[0]["session_id"] == runner.calls[1]["session_id"] == "ctx-1"


# ---------- Track H4：Context 严格schema ----------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context",
    [
        {"current_datetime": "not-a-date"},
        {"timezone": "Mars/Olympus"},
        {"locale": "en-US"},
        {"attachment_references": [{"reference_id": "a1"}]},  # 缺resource_type
        {
            "attachment_references": [
                {
                    "reference_id": "a1",
                    "resource_type": "doc",
                    "local_path": "/etc/passwd",
                }
            ]
        },
        {"unknown_key": "x"},
        {"conversation_summary": "前文含 access_token=abc"},
    ],
)
async def test_context_strict_schema_rejects_invalid(context):
    """非法datetime/timezone/locale/附件/未知键 → contract_error。"""
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=FakeRunner()
    )
    result = await runtime.invoke(_payload(context=context))
    assert result.error_code == "contract_error", context


@pytest.mark.asyncio
async def test_context_valid_values_accepted():
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=FakeRunner(),
        attachment_resolver=_supported_attachment_resolver(),
    )
    result = await runtime.invoke(
        _payload(
            context={
                "timezone": "Asia/Shanghai",
                "current_datetime": "2026-08-26T10:00:00+08:00",
                "locale": "zh-CN",
                "conversation_summary": "用户此前咨询过年假制度。",
                "attachment_references": [
                    {
                        "reference_id": "ref-1",
                        "resource_type": "document",
                        "display_name": "请假制度.pdf",
                        "media_type": "application/pdf",
                    }
                ],
            }
        )
    )
    assert result.status == "completed"
    assert result.error_code is None


@pytest.mark.asyncio
async def test_conversation_summary_isolated_from_user_text():
    """摘要进入独立【历史摘要】区块，不与正文混合。"""
    runner = FakeRunner(answer="好的。")
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=runner
    )
    await runtime.invoke(
        _payload(
            context={"conversation_summary": "前文：用户咨询了年假天数。"}
        )
    )
    messages = runner.calls[0]["messages"]
    assert "【历史摘要】" in messages
    assert messages.index("【历史摘要】") < messages.index("我的年假余额还有多少？")
    assert "不是当前指令" in messages


@pytest.mark.asyncio
async def test_attachment_references_not_dumped_into_prompt():
    runner = FakeRunner(answer="好的。")
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=runner,
        attachment_resolver=_supported_attachment_resolver(),
    )
    await runtime.invoke(
        _payload(
            message="这份文件说了什么",
            context={
                "attachment_references": [
                    {"reference_id": "ref-1", "resource_type": "document"}
                ]
            }
        )
    )
    # 附件引用/内容不写进用户消息 prompt；附件走独立 doc context（经 remote Consult）。
    assert "ref-1" not in runner.calls[0]["messages"]


@pytest.mark.asyncio
async def test_current_datetime_invalid_no_silent_fallback():
    """非法current_datetime必须contract_error，不得静默用server时钟。"""
    runtime = HrAssistantRuntime(
        remote_router=FakeRemoteRouter(None), local_runner=FakeRunner()
    )
    result = await runtime.invoke(
        _payload(context={"current_datetime": "2026/08/26 10:00"})
    )
    assert result.error_code == "contract_error"
