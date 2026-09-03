"""批次3：顶层公共A2A Provider单元测试（假runtime，不起真实模型）。"""

import pytest
from a2a.types import AgentCard, Message, Part, Role, TextPart

from apps.orchestrator.public_a2a.card import build_agent_card
from apps.orchestrator.public_a2a.executor import (
    HrAssistantExecutor,
    PublicContractError,
    _extract_payload,
)
from apps.orchestrator.public_runtime.result import (
    completed,
    failed,
    input_required,
    rejected,
)


PUBLIC_URL = "https://hr-assistant.example.invalid"
FORBIDDEN = (
    "root_agent", "hr_orchestrator", "leave_agent",
    "hr-consult-agent", "hr-employee-data-agent",
    "veadk", "veADK", "AgentKit", "agentkit", "Gaia",
)


def test_top_level_card_identity_and_capabilities():
    card = build_agent_card(PUBLIC_URL)
    assert card.name == "hr-assistant"
    assert card.version == "1.0.0"
    assert card.protocol_version == "0.3.0"
    assert card.preferred_transport == "JSONRPC"
    assert card.url == f"{PUBLIC_URL}/"
    assert [skill.id for skill in card.skills] == [
        "leave-and-attendance-service",
        "employee-self-service",
        "hr-policy-and-benefits-consultation",
        "hr-system-and-document-assistance",
    ]
    # 能力是任务领域，不是Tool名。
    serialized = card.model_dump_json(by_alias=True, exclude_none=True)
    for toolish in ("submit_leave", "get_schedule", "get_leave_balance"):
        assert toolish not in serialized


def test_top_level_card_no_internal_leak_and_roundtrip():
    card = build_agent_card(PUBLIC_URL)
    serialized = card.model_dump_json(by_alias=True, exclude_none=True)
    for term in FORBIDDEN:
        assert term not in serialized, term
    payload = card.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert AgentCard.model_validate(payload) == card
    assert "securitySchemes" not in payload  # Secret为0


def _message(text: str, metadata: dict | None = None) -> Message:
    return Message(
        message_id="msg-1",
        role=Role.user,
        parts=[Part(root=TextPart(text=text))],
        context_id="ctx-1",
        metadata=metadata,
    )


class _Ctx:
    def __init__(self, message: Message, task_id: str | None = "task-1"):
        self.message = message
        self.task_id = task_id
        self.context_id = "ctx-1"
        self.current_task = None


def test_extract_payload_allows_contract_metadata():
    ctx = _Ctx(
        _message(
            "明天请一天年休假",
            metadata={
                "execution_subject": {"subject_id": "snow-user-1"},
                "timezone": "Asia/Shanghai",
                "current_datetime": "2026-08-25T11:00:00",
                "locale": "zh-CN",
            },
        )
    )
    payload = _extract_payload(ctx)
    assert payload["message"] == "明天请一天年休假"
    assert payload["context_id"] == "ctx-1"
    assert payload["task_id"] == "task-1"
    assert payload["execution_subject"] == {"subject_id": "snow-user-1"}
    assert payload["context"]["timezone"] == "Asia/Shanghai"
    assert "execution_subject" not in payload["context"]


def test_extract_payload_rejects_unknown_metadata():
    ctx = _Ctx(_message("你好", metadata={"caller_agent": "hr_orchestrator"}))
    with pytest.raises(PublicContractError):
        _extract_payload(ctx)


def test_extract_payload_rejects_empty_text():
    ctx = _Ctx(_message("   "))
    with pytest.raises(PublicContractError):
        _extract_payload(ctx)


class FakeQueue:
    def __init__(self):
        self.events = []

    async def enqueue_event(self, event):
        self.events.append(event)


class FakeUpdater:
    # 通过monkeypatch替换TaskUpdater。
    def __init__(self, queue, task_id, context_id):
        self.queue, self.task_id, self.context_id = queue, task_id, context_id
        self.calls = []

    async def start_work(self):
        self.calls.append("start_work")

    async def add_artifact(self, parts, name=None, last_chunk=None):
        self.calls.append(("artifact", name))

    async def complete(self):
        self.calls.append("complete")

    async def requires_input(self, final=None):
        self.calls.append("requires_input")

    async def reject(self):
        self.calls.append("reject")

    async def failed(self):
        self.calls.append("failed")

    async def cancel(self):
        self.calls.append("cancel")


class FakeRuntime:
    def __init__(self, result):
        self.result = result
        self.payloads = []

    async def invoke(self, payload):
        self.payloads.append(payload)
        return self.result


@pytest.fixture
def patch_updater(monkeypatch):
    import apps.orchestrator.public_a2a.executor as executor_module

    monkeypatch.setattr(
        executor_module, "TaskUpdater", FakeUpdater, raising=True
    )


async def _run_executor(runtime_result):
    runtime = FakeRuntime(runtime_result)
    executor = HrAssistantExecutor(runtime)
    queue = FakeQueue()
    ctx = _Ctx(_message("你好"))
    await executor.execute(ctx, queue)
    return runtime, queue


@pytest.mark.asyncio
async def test_executor_completed_maps_to_complete(patch_updater):
    runtime, queue = await _run_executor(
        completed(request_id="task-1", answer="你好，我是企业人力智能助手。")
    )
    assert queue.events  # new_task + status事件
    assert runtime.payloads[0]["message"] == "你好"
    updater = queue.events  # 不再检查内部；终态通过FakeUpdater.calls确认


@pytest.mark.asyncio
async def test_executor_input_required_maps_to_requires_input(patch_updater, monkeypatch):
    import apps.orchestrator.public_a2a.executor as executor_module

    calls = []

    class RecordingUpdater(FakeUpdater):
        async def requires_input(self, final=None):
            calls.append(("requires_input", final))
            await super().requires_input(final)

    monkeypatch.setattr(executor_module, "TaskUpdater", RecordingUpdater)
    await _run_executor(
        input_required(request_id="task-1", answer="请问假期类型和日期？")
    )
    assert calls == [("requires_input", True)]


@pytest.mark.asyncio
async def test_executor_rejected_and_failed_map_to_terminal_states(patch_updater, monkeypatch):
    import apps.orchestrator.public_a2a.executor as executor_module

    states = []

    class RecordingUpdater(FakeUpdater):
        async def reject(self):
            states.append("reject")
            await super().reject()

        async def failed(self):
            states.append("failed")
            await super().failed()

    monkeypatch.setattr(executor_module, "TaskUpdater", RecordingUpdater)
    await _run_executor(
        rejected(request_id="task-1", answer="当前身份无法查询。",
                 error_code="identity_unverified")
    )
    await _run_executor(
        failed(request_id="task-2", answer="稍后重试。", error_code="failed")
    )
    assert states == ["reject", "failed"]


def test_build_app_keeps_card_and_health_without_contract_discovery():
    """架构澄清：AgentCard发现与健康检查保留为协议证据；
    远程运行时不再暴露合同发现端点——合同是运营方导入的显式请求工件。"""
    from apps.orchestrator.public_a2a.server import build_public_a2a_app
    from apps.orchestrator.public_a2a.settings import PublicA2ASettings

    class _Runtime:
        pass

    settings = PublicA2ASettings(
        listen_host="127.0.0.1",
        listen_port=8100,
        public_base_url=PUBLIC_URL,
        auth_mode="none",
    )
    app = build_public_a2a_app(runtime=_Runtime(), settings=settings)
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    # SDK默认提供 /.well-known/agent-card.json。
    assert "/.well-known/agent-card.json" in paths
    assert "/.well-known/agent-contract.json" not in paths


@pytest.mark.asyncio
async def test_executor_resumes_current_task_instead_of_new_task(patch_updater, monkeypatch):
    """input-required后客户端引用原taskId续发消息 → 继续同一任务。"""
    import apps.orchestrator.public_a2a.executor as executor_module

    resume_refs = []

    class RecordingUpdater(FakeUpdater):
        def __init__(self, queue, task_id, context_id):
            super().__init__(queue, task_id, context_id)
            resume_refs.append((task_id, context_id))

    monkeypatch.setattr(executor_module, "TaskUpdater", RecordingUpdater)

    runtime = FakeRuntime(
        completed(request_id="task-1", answer="申请已提交。")
    )
    executor = HrAssistantExecutor(runtime)
    queue = FakeQueue()

    existing_task = type("T", (), {"id": "task-resume", "context_id": "ctx-1"})()
    ctx = _Ctx(_message("年休假，明天一天"))
    ctx.current_task = existing_task
    ctx.task_id = "task-resume"

    await executor.execute(ctx, queue)
    assert resume_refs == [("task-resume", "ctx-1")]
    assert runtime.payloads[0]["request_id"] == "task-resume"
    # 未创建新任务：queue里只有状态/工件事件。
    task_events = [e for e in queue.events if getattr(e, "kind", None) is not None]
    assert all(getattr(e, "id", "task-resume") == "task-resume" for e in task_events)


@pytest.mark.asyncio
async def test_unknown_execution_cannot_claim_cancellation():
    """没有受控执行记录时不可虚报取消。"""
    from a2a.types import TaskNotCancelableError
    from a2a.utils.errors import ServerError

    executor = HrAssistantExecutor(FakeRuntime(None))
    with pytest.raises(ServerError) as exc_info:
        await executor.cancel(_Ctx(_message("你好")), FakeQueue())
    assert isinstance(exc_info.value.error, TaskNotCancelableError)
