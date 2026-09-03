"""WP-04 考勤计算：工具层、runtime 状态映射、A2A 校验。"""

import pytest

from apps.consult_agent.tools.attendance_calculation import attendance_calculation
from apps.consult_agent.runtime import _question_category, ConsultTurn
from apps.orchestrator.a2a.router import _validate_consult_calculation
from packages.agent_runtime.a2a.client import A2AInvocationError


def test_tool_deducts_and_returns_auditable_records():
    r = attendance_calculation(
        [{"kind": "late", "duration": "20分钟"}, {"kind": "late", "duration": "10分钟"}],
        monthly_exempt={"late_prior_exempt": 2},
    )
    assert r["success"] is True
    data = r["data"]
    assert data["total_deduction"] == 60.0
    assert data["total_absence_days"] == 0.0
    assert len(data["records"]) == 2
    # 可审计：每条含原时长/桶/金额/豁免
    assert data["records"][0]["original_minutes"] == 20
    assert data["records"][0]["deduction"] == 40.0
    assert data["records"][1]["deduction"] == 20.0


def test_tool_need_more_info_when_exempt_context_missing():
    r = attendance_calculation([{"kind": "late", "duration": "8分钟"}], monthly_exempt=None)
    assert r["success"] is False
    assert r["error_type"] == "need_more_information"


def test_tool_severe_absence_no_deduction():
    r = attendance_calculation([{"kind": "late", "duration": "65分钟"}])
    data = r["data"]
    assert data["total_absence_days"] == 0.5
    assert data["total_deduction"] == 0.0


def test_tool_ambiguous_duration_insufficient():
    r = attendance_calculation([{"kind": "late", "duration": "大概半小时"}])
    assert r["success"] is False
    assert r["error_type"] == "insufficient_attendance_duration"


def test_tool_unit_hour():
    r = attendance_calculation([{"kind": "early_leave", "duration": "1.5小时"}])
    assert r["data"]["records"][0]["original_minutes"] == 90


def test_question_category_attendance():
    turn = ConsultTurn(answer="", tool_names=["attendance_calculation"])
    assert _question_category("迟到17分钟扣多少？", turn) == "attendance_calculation"


def test_question_category_policy_not_attendance():
    turn = ConsultTurn(answer="", tool_names=["kb_search"], knowledge_scope="policy")
    assert _question_category("公司迟到扣款规定是什么？", turn) == "hr_policy"


def test_validate_consult_calculation_pass():
    _validate_consult_calculation({
        "question_category": "attendance_calculation",
        "answer": "总扣款60元，旷工0天。",
        "calculation": {"total_deduction": 60, "total_absence_days": 0, "records": []},
    })


def test_validate_consult_calculation_missing_calc():
    with pytest.raises(A2AInvocationError):
        _validate_consult_calculation({
            "question_category": "attendance_calculation",
            "answer": "总扣款60元",
            "calculation": None,
        })


def test_validate_consult_calculation_number_mismatch():
    with pytest.raises(A2AInvocationError):
        _validate_consult_calculation({
            "question_category": "attendance_calculation",
            "answer": "总扣款40元，旷工0天。",
            "calculation": {"total_deduction": 60, "total_absence_days": 0, "records": []},
        })
