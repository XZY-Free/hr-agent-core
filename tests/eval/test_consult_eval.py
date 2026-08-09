"""独立hr-consult-agent的10条真实模型与Knowledge评测。"""

import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from apps.consult_agent.a2a.contract import ConsultA2ARequest
from apps.consult_agent.runtime import ConsultObservation, build_consult_runtime


DUMMY_KEY = "dummy-for-struct-test-only"
CASES_PATH = Path(__file__).with_name("consult_cases.yaml")
LOG_DIR = Path(__file__).with_name("logs")


def _has_real_config() -> bool:
    key = os.getenv("MODEL_AGENT_API_KEY")
    required = (
        "VOLCENGINE_ACCESS_KEY",
        "VOLCENGINE_SECRET_KEY",
        "KB_COLLECTION_POLICY",
        "KB_COLLECTION_HANDBOOK",
        "KB_COLLECTION_SALARY",
        "KB_COLLECTION_CHILDCARE",
    )
    return (
        bool(key)
        and key != DUMMY_KEY
        and os.getenv("KB_BACKEND") == "agentkit"
        and all(os.getenv(name, "").strip() for name in required)
    )


CASES = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
pytestmark = [
    pytest.mark.eval,
    pytest.mark.consult_eval,
    pytest.mark.skipif(
        not _has_real_config(),
        reason="独立Consult评测需要真实模型与Viking配置",
    ),
]


class _DocumentResponse:
    status_code = 200
    headers = {"Content-Length": "400"}

    def iter_content(self, chunk_size=8192):
        yield (
            "# 2026 年春节假期安排通知\n\n"
            "一、放假时间：2 月 16 日至 2 月 22 日，共 7 天。\n"
            "二、值班安排：各部门排定值班表并报人力资源部备案。\n"
            "三、考勤要求：节前节后工作日均需正常打卡。\n"
        ).encode()

    def raise_for_status(self):
        return None


@pytest.fixture(scope="module")
def observations():
    return []


@pytest.fixture(scope="module")
def consult_runtime(observations):
    return build_consult_runtime(observer=observations.append)


@pytest.fixture(scope="module")
def consult_eval_log():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"consult-eval-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    yield path
    print(f"\n[consult-eval] 脱敏证据：{path}")


def _assert_case(case, result, observation: ConsultObservation):
    if expected := case.get("status"):
        assert result.status == expected
    else:
        assert result.status in case["status_any"]
    assert result.request_id == observation.request_id
    assert observation.status == result.status
    if expected := case.get("tool"):
        assert expected in observation.tool_names
    if forbidden := case.get("forbidden_tool"):
        assert forbidden not in observation.tool_names
    if expected := case.get("scope"):
        assert result.knowledge_scope == expected
    if error_code := case.get("error_code"):
        assert result.error_code == error_code
    for keyword in case.get("keywords", []):
        assert keyword in result.answer
    if keywords := case.get("any_keywords"):
        assert any(keyword in result.answer for keyword in keywords)
    for keyword in case.get("forbidden_keywords", []):
        assert keyword not in result.answer
    if "kb_search" in observation.tool_names and result.status == "succeeded":
        assert result.sources
        assert all(source.source and isinstance(source.score, float) for source in result.sources)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
async def test_consult_eval_case(
    case,
    monkeypatch,
    observations,
    consult_runtime,
    consult_eval_log,
):
    import apps.consult_agent.tools.parse_document as parse_document_module

    monkeypatch.setattr(
        parse_document_module.requests,
        "get",
        lambda *args, **kwargs: _DocumentResponse(),
    )
    request_id = str(uuid4())
    before = len(observations)
    result = await consult_runtime.run(ConsultA2ARequest(
        request_id=request_id,
        user_id="consult-eval-user",
        session_id=f"consult-eval-{case['id']}-{request_id}",
        caller_agent="hr_orchestrator",
        locale="zh-CN",
        message=case["message"],
        context_summary="",
    ))
    assert len(observations) == before + 1
    observation = observations[-1]
    _assert_case(case, result, observation)

    quality = {
        keyword: keyword in result.answer
        for keyword in case.get("quality_keywords", [])
    }
    evidence = {
        "case": case["id"],
        "request_id": request_id,
        "status": result.status,
        "scope": result.knowledge_scope,
        "tools": list(observation.tool_names),
        "source_count": len(result.sources),
        "error_code": result.error_code,
        "quality": quality,
    }
    with consult_eval_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(evidence, ensure_ascii=False) + "\n")
