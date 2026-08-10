"""独立Employee Data Agent三条真实模型与显式Stub评测。"""

import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from apps.employee_data_agent.a2a.contract import EmployeeDataA2ARequest
from apps.employee_data_agent.identity import TrustedIdentityResolver
from apps.employee_data_agent.provider import StubEmployeeDataProvider
from apps.employee_data_agent.runtime import (
    EmployeeDataObservation,
    EmployeeDataRuntime,
    VeADKEmployeeDataTurnRunner,
)
from apps.employee_data_agent.agent import build_employee_data_agent
from packages.agent_runtime.model_config import extra_config_for, model_for


DUMMY_KEY = "dummy-for-struct-test-only"
CASES = yaml.safe_load(Path(__file__).with_name("employee_data_cases.yaml").read_text())
LOG_DIR = Path(__file__).with_name("logs")


def _has_real_key() -> bool:
    key = os.getenv("MODEL_AGENT_API_KEY")
    return bool(key) and key != DUMMY_KEY


pytestmark = [
    pytest.mark.eval,
    pytest.mark.employee_data_eval,
    pytest.mark.skipif(not _has_real_key(), reason="Employee Data评测需要真实模型Key"),
]


def _provider():
    return StubEmployeeDataProvider({
        "EMP-001": {
            "annual_leave": {
                "mode": "flat", "quota": 5,
                "balance": [{"leave_name": "年休假", "total": 5, "used": 1, "remain": 4}],
            },
            "employment": {
                "social_service_year": "6", "social_service_month": "4",
                "social_service_day": "0", "hire_month": "11", "hire_day": "03",
            },
            "medical_period": {"quota": 24, "used": 3, "balance": 21},
        }
    })


@pytest.fixture(scope="module")
def observations():
    return []


@pytest.fixture(scope="module")
def runtime(observations):
    agent = build_employee_data_agent(
        model_name=model_for("employee_data"),
        model_extra_config=extra_config_for("employee_data"),
    )
    return EmployeeDataRuntime(
        identity_resolver=TrustedIdentityResolver(
            {"employee-eval-user": "EMP-001"},
            ref_secret="employee-eval-ref-secret",
        ),
        turn_runner=VeADKEmployeeDataTurnRunner(agent, _provider()),
        observer=observations.append,
    )


@pytest.fixture(scope="module")
def evidence_path():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"employee-data-eval-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    yield path
    print(f"\n[employee-data-eval] 脱敏证据：{path}")


def _value_at(data: dict, path: str):
    value = data
    for segment in path.split("."):
        value = value[segment]
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
async def test_employee_data_eval_case(case, runtime, observations, evidence_path):
    request_id = str(uuid4())
    before = len(observations)
    result = await runtime.run(EmployeeDataA2ARequest(
        request_id=request_id,
        user_id="employee-eval-user",
        session_id=f"employee-eval-{case['id']}-{request_id}",
        caller_agent="hr_orchestrator",
        locale="zh-CN",
        message=case["message"],
        context_summary="",
    ))
    assert len(observations) == before + 1
    observation: EmployeeDataObservation = observations[-1]
    assert result.status == "succeeded"
    assert result.query_type == case["query_type"]
    assert result.source == "stub"
    assert observation.tool_name == case["tool"]
    assert observation.source == "stub"
    assert _value_at(result.data, case["expected_path"]) == case["expected_value"]
    assert "kb_search" not in observation.tool_name

    with evidence_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "case": case["id"],
            "request_id": request_id,
            "status": result.status,
            "query_type": result.query_type,
            "source": result.source,
            "tool": observation.tool_name,
            "employee_ref": result.employee_ref,
            "data_keys": sorted(result.data),
        }, ensure_ascii=False) + "\n")
