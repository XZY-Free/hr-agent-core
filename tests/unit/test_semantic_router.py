"""WP-05 语义路由与 continuation owner 测试。"""

import pytest

from apps.orchestrator.a2a.routing import DeterministicRouteTable, RouteTarget
from apps.orchestrator.a2a.semantic_router import (
    Confidence,
    Intent,
    RouteDecision,
    RouteTarget as SemanticTarget,
    SemanticRouter,
    default_classifier,
    safe_decision,
)


# ---------- 意图分类（default_classifier） ----------

@pytest.mark.parametrize("text", [
    "我想休年假", "帮我请个假", "明天想调休", "后天下午不在",
    "我要补登昨天病假", "上一个假改成后天", "时间不对，改成16点",
    "原因换成复诊", "年假改病假", "请一天事假",
])
def test_leave_intent(text):
    d = safe_decision(Intent(semantic := default_classifier(text)["intent"]), Confidence.HIGH)
    assert d.target is SemanticTarget.LOCAL


@pytest.mark.parametrize("text", [
    "我年假还有多少", "我的育儿假剩几天", "我有哪些假没休",
    "查下本人调休余额", "我工龄几年", "今年年休假折算多少",
    "我的医疗期余额",
])
def test_employee_data_intent(text):
    assert default_classifier(text)["intent"] == Intent.EMPLOYEE_SELF_DATA.value


@pytest.mark.parametrize("text", [
    "年假能跨年吗", "育儿假怎么申请", "四川育儿假几天",
    "病假需要证明吗", "HR系统怎么补卡", "公司迟到制度是什么",
])
def test_consult_intent(text):
    assert default_classifier(text)["intent"] == Intent.HR_CONSULTATION.value


@pytest.mark.parametrize("text", [
    "迟到17分钟扣多少", "早退65分钟算什么", "第三次迟到8分钟多少钱",
    "迟到50分钟扣多少",
])
def test_attendance_intent(text):
    assert default_classifier(text)["intent"] == Intent.ATTENDANCE_CALCULATION.value


@pytest.mark.parametrize("text", ["年假", "育儿假", "迟到", "调休"])
def test_ambiguous_intent(text):
    # 缺上下文的词 → needs_clarification，不默认 Consult。
    assert default_classifier(text)["intent"] == Intent.NEEDS_CLARIFICATION.value


# ---------- RouteDecision 固定映射 ----------

def test_safe_decision_fixed_target_mapping():
    assert safe_decision(Intent.LEAVE_TRANSACTION, Confidence.HIGH).target is SemanticTarget.LOCAL
    assert safe_decision(Intent.EMPLOYEE_SELF_DATA, Confidence.HIGH).target is SemanticTarget.EMPLOYEE_DATA
    assert safe_decision(Intent.HR_CONSULTATION, Confidence.HIGH).target is SemanticTarget.CONSULT
    assert safe_decision(Intent.ATTENDANCE_CALCULATION, Confidence.HIGH).target is SemanticTarget.CONSULT
    assert safe_decision(Intent.GENERAL_LOCAL, Confidence.HIGH).target is SemanticTarget.LOCAL
    assert safe_decision(Intent.NEEDS_CLARIFICATION, Confidence.LOW).target is SemanticTarget.LOCAL


def test_unknown_intent_never_defaults_consult():
    decision = SemanticRouter()._parse({"intent": "bogus", "confidence": "high"})
    assert decision.intent is Intent.NEEDS_CLARIFICATION
    assert decision.target is SemanticTarget.LOCAL


def test_semantic_router_unavailable_classifier_safe():
    router = SemanticRouter(classifier=None)
    # 无 classifier 也应安全兜底 local，不 Consult。
    decision = router.classify("帮我查下育儿假", {})
    assert decision.target is SemanticTarget.LOCAL


# ---------- guard + 语义路由 ----------

def _table():
    return DeterministicRouteTable()


def test_ordinary_business_routed_by_semantics_not_regex():
    table = _table()
    assert table.decide("我还有几天年假", user_id="u", session_id="s") == RouteTarget.EMPLOYEE_DATA
    assert table.decide("迟到扣款制度是什么", user_id="u", session_id="s") == RouteTarget.CONSULT


def test_no_match_defaults_local_not_consult():
    table = _table()
    assert table.decide("年假", user_id="u", session_id="s") == RouteTarget.LOCAL


def test_continuation_owner_prioritizes_over_reclassification():
    table = _table()
    table.record_remote_status(
        user_id="u", session_id="s", target=RouteTarget.CONSULT,
        status="need_more_information", task_id="task-a",
    )
    # task-a 补充："四川" 回 consult，不重分类。
    assert table.decide("四川", user_id="u", session_id="s",
                        task_id="task-a") == RouteTarget.CONSULT
    # 不同 task 不劫持 owner → 独立分类。
    assert table.decide("公司年假制度", user_id="u", session_id="s",
                        task_id="task-b") == RouteTarget.CONSULT
    assert table.decide("四川", user_id="u", session_id="s",
                        task_id="task-b") == RouteTarget.LOCAL  # 独立分类 → 低置信 local


def test_terminal_status_clears_owner():
    table = _table()
    table.record_remote_status(
        user_id="u", session_id="s", target=RouteTarget.CONSULT,
        status="need_more_information", task_id="task-a",
    )
    table.record_remote_status(
        user_id="u", session_id="s", target=RouteTarget.CONSULT,
        status="succeeded", task_id="task-a",
    )
    assert table.decide("四川", user_id="u", session_id="s",
                        task_id="task-a") == RouteTarget.LOCAL


def test_fake_action_routes_preserved():
    table = _table()
    assert table.decide("打开打卡明细", user_id="u", session_id="s") == RouteTarget.LOCAL
    assert table.decide("转人工", user_id="u", session_id="s") == RouteTarget.LOCAL
    assert table.decide("取消昨天的请假", user_id="u", session_id="s") == RouteTarget.LOCAL
