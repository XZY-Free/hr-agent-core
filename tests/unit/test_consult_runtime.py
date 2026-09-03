"""独立Consult运行时职责和状态映射测试。"""

import pytest

from apps.consult_agent.a2a.contract import ConsultA2ARequest
from apps.consult_agent.runtime import (
    ConsultObservation,
    ConsultRuntime,
    ConsultTurn,
    validate_standalone_config,
)


class RecordingTurnRunner:
    def __init__(self, turn: ConsultTurn):
        self.turn = turn
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return self.turn


def _request(message: str) -> ConsultA2ARequest:
    return ConsultA2ARequest(
        request_id="request-a",
        user_id="user-a",
        session_id="session-a",
        caller_agent="hr_orchestrator",
        locale="zh-CN",
        message=message,
        context_summary="",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "error_code"),
    [
        ("我还有几天年假", "personal_data_not_allowed"),
        ("明天请一天年假", "leave_request_not_allowed"),
        ("我电脑坏了怎么报修", "out_of_scope"),
    ],
)
async def test_rejected_requests_never_reach_model_runner(message, error_code):
    runner = RecordingTurnRunner(ConsultTurn(answer="不应调用"))
    runtime = ConsultRuntime(turn_runner=runner)

    result = await runtime.run(_request(message))

    assert result.status == "rejected"
    assert result.error_code == error_code
    assert runner.requests == []
    assert not result.sources


@pytest.mark.asyncio
async def test_knowledge_success_preserves_scope_source_and_zero_score():
    runner = RecordingTurnRunner(ConsultTurn(
        answer="制度答案",
        tool_names=["kb_search"],
        knowledge_scope="policy",
        sources=[{"source": "制度.docx", "score": 0.0}],
    ))
    runtime = ConsultRuntime(turn_runner=runner)

    result = await runtime.run(_request("迟到扣款制度是什么"))

    assert result.status == "succeeded"
    assert result.knowledge_scope == "policy"
    assert result.model_dump()["sources"] == [{"source": "制度.docx", "score": 0.0}]


@pytest.mark.asyncio
async def test_missing_childcare_province_requires_information_but_keeps_session_turn():
    runner = RecordingTurnRunner(ConsultTurn(
        answer="", input_question="请问您所在的省份是哪里？",
    ))
    runtime = ConsultRuntime(turn_runner=runner)

    result = await runtime.run(_request("育儿假有几天"))

    assert result.status == "need_more_information"
    assert result.question_category == "childcare_policy"
    assert len(runner.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["深圳育儿假", "育儿假有几天", "你好"])
async def test_answer_without_explicit_input_request_never_opens_form(message):
    runner = RecordingTurnRunner(ConsultTurn(
        answer="已经回答了您的问题。您可能还想了解：申请材料有哪些？",
        tool_names=["kb_search"],
        knowledge_scope="childcare",
        sources=[{"source": "政策", "score": 0.8}],
    ))
    result = await ConsultRuntime(turn_runner=runner).run(_request(message))
    assert result.status == "succeeded"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("turn", "status", "error_code"),
    [
        (ConsultTurn(answer="暂时没有查到相关制度", tool_names=["kb_search"],
                     knowledge_scope="policy", sources=[]), "not_found", "knowledge_not_found"),
        (ConsultTurn(answer="知识库暂不可用", tool_names=["kb_search"],
                     error_code="knowledge_network_error"),
         "temporarily_unavailable", "knowledge_network_error"),
        (ConsultTurn(answer="知识库暂不可用", tool_names=["kb_search"],
                     error_code="kb_unavailable"),
         "temporarily_unavailable", "kb_unavailable"),
    ],
)
async def test_not_found_and_knowledge_failure_have_distinct_statuses(turn, status, error_code):
    runtime = ConsultRuntime(turn_runner=RecordingTurnRunner(turn))

    result = await runtime.run(_request("火星基地宠物报销制度"))

    assert result.status == status
    assert result.error_code == error_code


@pytest.mark.asyncio
async def test_observation_records_only_safe_execution_metadata(caplog):
    observations: list[ConsultObservation] = []
    runner = RecordingTurnRunner(ConsultTurn(
        answer="不得进入日志的制度正文",
        tool_names=["kb_search"],
        knowledge_scope="policy",
        sources=[{"source": "制度.docx", "score": 0.3}],
    ))
    runtime = ConsultRuntime(turn_runner=runner, observer=observations.append)

    with caplog.at_level("INFO", logger="apps.consult_agent.runtime"):
        await runtime.run(_request("不得进入日志的用户问题"))

    assert len(observations) == 1
    assert observations[0].tool_names == ("kb_search",)
    assert observations[0].knowledge_scope == "policy"
    assert "tools=kb_search" in caplog.text
    assert "不得进入日志" not in caplog.text
    assert "制度.docx" not in caplog.text


@pytest.mark.asyncio
async def test_model_out_of_scope_answer_is_not_mislabeled_as_success():
    runner = RecordingTurnRunner(ConsultTurn(
        answer="该问题不属于人力资源范畴，建议咨询行政管理部门。",
        tool_names=[],
    ))
    runtime = ConsultRuntime(turn_runner=runner)

    result = await runtime.run(_request("公司对宠物入职有什么规定"))

    assert result.status == "rejected"
    assert result.error_code == "out_of_scope"


def test_standalone_config_fails_closed_when_collection_is_missing(monkeypatch):
    required = {
        "MODEL_AGENT_API_KEY": "model-key",
        "KB_BACKEND": "agentkit",
        "VOLCENGINE_ACCESS_KEY": "ak",
        "VOLCENGINE_SECRET_KEY": "sk",
        "KB_COLLECTION_POLICY": "policy",
        "KB_COLLECTION_HANDBOOK": "handbook",
        "KB_COLLECTION_SALARY": "salary",
        "KB_COLLECTION_CHILDCARE": "childcare",
    }
    for name, value in required.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("KB_COLLECTION_CHILDCARE")

    with pytest.raises(RuntimeError, match="KB_COLLECTION_CHILDCARE"):
        validate_standalone_config()


def test_standalone_config_does_not_require_gaia_or_employee_identity(monkeypatch):
    for name in (
        "employeeId",
        "corp_id",
        "client_secret",
        "grant_type",
        "GAIA_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "MODEL_AGENT_API_KEY": "model-key",
        "KB_BACKEND": "agentkit",
        "VOLCENGINE_ACCESS_KEY": "ak",
        "VOLCENGINE_SECRET_KEY": "sk",
        "KB_COLLECTION_POLICY": "policy",
        "KB_COLLECTION_HANDBOOK": "handbook",
        "KB_COLLECTION_SALARY": "salary",
        "KB_COLLECTION_CHILDCARE": "childcare",
    }.items():
        monkeypatch.setenv(name, value)

    validate_standalone_config()
