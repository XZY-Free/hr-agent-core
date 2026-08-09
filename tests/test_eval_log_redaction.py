"""评测证据脱敏与核心/质量门禁分类。"""

from tests.eval.test_eval import (
    _evaluate_quality_metrics,
    _format_trace,
    _redact_tool_response,
)


def test_kb_search_trace_keeps_source_score_but_removes_content():
    response = {
        "success": True,
        "data": [{
            "content": "内部制度完整切片正文",
            "source": "考勤制度.docx",
            "score": 0.0,
        }],
    }

    redacted = _redact_tool_response("kb_search", response)

    assert "内部制度完整切片正文" not in str(redacted)
    assert redacted == {
        "success": True,
        "result_count": 1,
        "results": [{"source": "考勤制度.docx", "score": 0.0}],
    }


def test_non_knowledge_tool_trace_response_is_unchanged():
    response = {"success": True, "data": {"leaveRemain": 4}}

    assert _redact_tool_response("get_leave_balance", response) is response


def test_followup_quality_metric_records_miss_without_raising():
    case = {
        "id": "followup_present",
        "quality_keywords": ["还想了解"],
    }

    metrics = _evaluate_quality_metrics(case, "年假可延期至次年3月31日。", "")

    assert metrics == [{
        "name": "recommended_followup",
        "keyword": "还想了解",
        "hit": False,
    }]


def test_trace_output_separates_core_result_and_quality_metric():
    rec = {
        "case": "followup_present",
        "offset": 0,
        "turns": [],
        "error": None,
        "core_outcome": "通过",
        "quality_metrics": [{
            "name": "recommended_followup",
            "keyword": "还想了解",
            "hit": False,
        }],
    }

    output = _format_trace(rec)

    assert "核心业务评测：通过" in output
    assert "非阻塞质量指标：recommended_followup=未命中" in output
