"""WP-04 考勤量化计算远端验收：一个业务不变量。

Consult 必须调用确定性 attendance_calculation，把一批迟到/早退记录按输入顺序作为
月度豁免状态转换处理；一般扣款、60/240 严重边界、单位换算、缺上下文与多记录累计都必须
通过公共 A2A 的 question_category=attendance_calculation 与 calculation 可审计，
answer 数字与 calculation 一致。LLM 只提取结构，不能成为算术 Authority。

范围：真实 HTTPS A2A 调用（AgentKit 开发 Runtime 的 consult）。无本地应用/模型/服务、
无 fake-model、无 ASGI。全部通过 business_support.request_task 直连 consult。
用身份 oracle 第一主体派生 internal_user_id，并复用 employee_message() 构造内部可信
A2A metadata（caller_agent=hr_orchestrator），每次请求新建 session。

安全：本文件不改任何生产代码；所有断言走 business_support._check()，失败消息不打印主体、
原始响应、answer、凭据；不得 mock/ASGI/localhost/skip/xfail；不 import apps/packages/
veadk。网络/协议失败必须让测试失败（request_task 直接抛出收敛后的 AcceptanceError）。

注：当前生产代码两个已知缺口——
- calculate_attendance() 对每条反复读取不可变 prior，不会在第一条免扣后增加本轮计数，
  故「两条迟到8分钟、此前免扣1次」应 RED（当前两条都免、total=0，应为 20）。
- _monthly_entry() 对只提供一侧的上下文把另一侧默认 0，故「早退此前次数未知」应 RED
  （当前把 early 当 0 直接算、状态 succeeded，应为 need_more_information）。
其它边界（一般/严重/单条豁免/分池/Golden/模糊/制度）可能绿。
"""

from __future__ import annotations

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 结构化 record 的严格字段集合（与 attendance_calculation 序列化逐字对齐）。
_RECORD_FIELDS = (
    "sequence", "kind", "original_minutes", "chargeable_bucket",
    "deduction", "absence_days", "exemption_applied", "is_severe",
)
_CALC_FIELDS = {"records", "total_deduction", "total_absence_days"}
_FORBIDDEN_TOKENS = ("employee_id", "secret", "token")


# --------------------------------------------------------------------------
# fixtures（与 WP-01/WP-03 一致：subject A 为 oracle 第一条）
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def identity_oracle() -> dict[str, OracleSubject]:
    return bs.load_identity_oracle()


@pytest.fixture(scope="session")
def subject_a(identity_oracle) -> OracleSubject:
    return list(identity_oracle.values())[0]


def _consult(subject: OracleSubject, text: str):
    """构造 Consult 内部可信 A2A 消息（caller_agent=hr_orchestrator，全新 session）。"""
    internal = bs.derive_internal_user_id(subject.subject_kind, subject.subject_id)
    return bs.employee_message(text, internal_user_id=internal)


# --------------------------------------------------------------------------
# 构造序列化 record 期望（bucket=None 表示严重记录）。
# --------------------------------------------------------------------------
def _rec(sequence, kind, original, bucket, deduction, absence, exempt, severe):
    return {
        "sequence": sequence,
        "kind": kind,
        "original_minutes": original,
        "chargeable_bucket": bucket,
        "deduction": deduction,
        "absence_days": absence,
        "exemption_applied": exempt,
        "is_severe": severe,
    }


# --------------------------------------------------------------------------
# 复用断言（均不打印主体/原始响应/answer/oracle/凭据）
# --------------------------------------------------------------------------
def _assert_no_sensitive(obj, *, label: str) -> None:
    """递归断言响应不含 employee_id/secret/token 字段或子串。"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            bs._check(key not in _FORBIDDEN_TOKENS, f"{label}泄露敏感字段")
            _assert_no_sensitive(value, label=label)
    elif isinstance(obj, list):
        for value in obj:
            _assert_no_sensitive(value, label=label)
    elif isinstance(obj, str):
        for token in _FORBIDDEN_TOKENS:
            bs._check(token not in obj, f"{label}响应含敏感子串")


def _assert_truthy(answer, *, label: str) -> None:
    bs._check(isinstance(answer, str) and answer.strip(), f"{label}answer为空")


def _assert_answer_total(answer, calc, *, label: str) -> None:
    """answer 至少要包含结构化总扣款/总旷工数字；0 值不强求（与生产校验一致）。"""
    _assert_truthy(answer, label=label)
    for key in ("total_deduction", "total_absence_days"):
        value = calc.get(key)
        bs._check(
            isinstance(value, (int, float)) and not isinstance(value, bool),
            f"{label}{key}非数值",
        )
        if value:
            forms = {str(value)}
            if isinstance(value, float) and value.is_integer():
                forms.add(str(int(value)))
            bs._check(
                any(form in answer for form in forms),
                f"{label}answer未含{key}数值",
            )


def _assert_calc(data, *, label: str) -> tuple[dict, list]:
    bs._check(data.get("status") == "succeeded", f"{label}未成功")
    bs._check(data.get("error_code") is None, f"{label}出现非预期错误码")
    bs._check(
        data.get("question_category") == "attendance_calculation",
        f"{label}question_category非attendance_calculation",
    )
    calc = data.get("calculation")
    bs._check(isinstance(calc, dict), f"{label}缺少calculation证据")
    bs._check(set(calc) == _CALC_FIELDS, f"{label}calculation字段不严格")
    records = calc.get("records")
    bs._check(isinstance(records, list) and records, f"{label}calculation.records缺失")
    return calc, records


def _assert_record(record, index, expected, *, label: str) -> None:
    bs._check(isinstance(record, dict), f"{label}record{index}非对象")
    bs._check(set(record) == set(_RECORD_FIELDS), f"{label}record{index}字段不严格")
    bs._check(set(expected) == set(_RECORD_FIELDS), f"{label}record{index}期望字段不合法")
    for field in _RECORD_FIELDS:
        exp = expected[field]
        got = record[field]
        if exp is None:
            bs._check(got is None, f"{label}record{index}.{field}应为None")
        else:
            bs._check(got == exp, f"{label}record{index}.{field}不一致")
    bs._check(record["sequence"] == index, f"{label}record{index}序号不连续")


def _assert_attendance(data, expected_records, *, label: str) -> None:
    calc, records = _assert_calc(data, label=label)
    bs._check(len(records) == len(expected_records), f"{label}记录条数不一致")
    total_ded = 0.0
    total_abs = 0.0
    for i, (got, exp) in enumerate(zip(records, expected_records), start=1):
        _assert_record(got, i, exp, label=label)
        total_ded += exp["deduction"]
        total_abs += exp["absence_days"]
    bs._check(calc.get("total_deduction") == total_ded, f"{label}total_deduction与记录累加不一致")
    bs._check(
        calc.get("total_absence_days") == total_abs,
        f"{label}total_absence与记录累加不一致",
    )
    _assert_answer_total(data.get("answer"), calc, label=label)
    _assert_no_sensitive(data, label=label)


def _assert_need_exempt(data, *, label: str, ask_token: str = "免") -> None:
    bs._check(data.get("status") == "need_more_information", f"{label}未判为need_more_information")
    bs._check(data.get("error_code") is None, f"{label}need_more_information携带非预期错误码")
    bs._check(
        data.get("question_category") == "attendance_calculation",
        f"{label}question_category非attendance_calculation",
    )
    bs._check(data.get("calculation") is None, f"{label}不应出现calculation")
    answer = data.get("answer")
    bs._check(isinstance(answer, str) and answer.strip(), f"{label}缺少追问answer")
    bs._check(ask_token in answer, f"{label}answer未询问月度免扣次数")


# --------------------------------------------------------------------------
# 场景1：一般边界（本月两类此前免扣都2次，避免缺上下文）
# --------------------------------------------------------------------------
_GENERAL_CASES = [
    ("本月此前迟到免扣2次、早退免扣2次，今天迟到11分钟扣多少？",
     [_rec(1, "late", 11, 20, 40.0, 0.0, False, False)]),
    ("本月此前迟到免扣2次、早退免扣2次，今天迟到59分钟扣多少？",
     [_rec(1, "late", 59, 60, 120.0, 0.0, False, False)]),
    ("本月此前迟到免扣2次、早退免扣2次，今天早退半小时扣多少？",
     [_rec(1, "early_leave", 30, 30, 60.0, 0.0, False, False)]),
]


@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize("message,expected_records", _GENERAL_CASES)
async def test_general_boundary(probes, subject_a, message, expected_records) -> None:
    data = await bs.request_task(probes, "consult", _consult(subject_a, message))
    _assert_attendance(data, expected_records, label="一般边界")


# --------------------------------------------------------------------------
# 场景2：严重边界（60/240）——严重记录只累计旷工，不叠加一般金额
# --------------------------------------------------------------------------
_SEVERE_CASES = [
    ("今天迟到60分钟怎么算？", [_rec(1, "late", 60, None, 0.0, 0.5, False, True)]),
    ("今天迟到239分钟算旷工几天？", [_rec(1, "late", 239, None, 0.0, 0.5, False, True)]),
    ("今天迟到240分钟算旷工几天？", [_rec(1, "late", 240, None, 0.0, 1.0, False, True)]),
    ("今天迟到250分钟算旷工几天？", [_rec(1, "late", 250, None, 0.0, 1.0, False, True)]),
    ("今天早退1.5小时怎么算？", [_rec(1, "early_leave", 90, None, 0.0, 0.5, False, True)]),
]


@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize("message,expected_records", _SEVERE_CASES)
async def test_severe_boundary(probes, subject_a, message, expected_records) -> None:
    data = await bs.request_task(probes, "consult", _consult(subject_a, message))
    _assert_attendance(data, expected_records, label="严重边界")


# --------------------------------------------------------------------------
# 场景3：单条豁免（此前迟到免扣 0/1/2 次 + 本次迟到8分钟）
# --------------------------------------------------------------------------
_EXEMPT_CASES = [
    ("本月此前迟到免扣0次，今天迟到8分钟扣多少？",
     [_rec(1, "late", 8, 10, 0.0, 0.0, True, False)]),
    ("本月此前迟到免扣1次，今天迟到8分钟扣多少？",
     [_rec(1, "late", 8, 10, 0.0, 0.0, True, False)]),
    ("本月此前迟到免扣2次，今天迟到8分钟扣多少？",
     [_rec(1, "late", 8, 10, 20.0, 0.0, False, False)]),
]


@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize("message,expected_records", _EXEMPT_CASES)
async def test_single_exemption(probes, subject_a, message, expected_records) -> None:
    data = await bs.request_task(probes, "consult", _consult(subject_a, message))
    _assert_attendance(data, expected_records, label="单条豁免")


# --------------------------------------------------------------------------
# 场景4：用户没给此前免扣次数 → 追问，不得假定 0/2
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_missing_monthly_exempt_need_info(probes, subject_a) -> None:
    data = await bs.request_task(probes, "consult", _consult(subject_a, "迟到8分钟扣多少？"))
    _assert_need_exempt(data, label="缺月度免扣次数")


# --------------------------------------------------------------------------
# 场景5：P1 根因——本轮两条迟到8分钟，此前免扣1次。
# 第一条用第2次免扣(true/0元)，随后本轮必须消费一次，第二条成为第3次(false/20元)。
# 禁止两条都读取 prior=1。当前生产重复读不可变 prior → 两条都免、total=0 → 应 RED。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_two_late_consume_exemption_sequence(probes, subject_a) -> None:
    message = "本月此前迟到免扣1次，今天又迟到8分钟、迟到8分钟，合计扣多少？"
    data = await bs.request_task(probes, "consult", _consult(subject_a, message))
    expected = [
        _rec(1, "late", 8, 10, 0.0, 0.0, True, False),
        _rec(2, "late", 8, 10, 20.0, 0.0, False, False),
    ]
    _assert_attendance(data, expected, label="双迟到跨免扣序列")


# --------------------------------------------------------------------------
# 场景6：迟到/早退分池——late=1、early=2 各自维护；顺序保持。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_late_and_early_separate_pools(probes, subject_a) -> None:
    message = "本月此前迟到免扣1次、早退免扣2次，今天迟到8分钟、早退8分钟，各扣多少？"
    data = await bs.request_task(probes, "consult", _consult(subject_a, message))
    expected = [
        _rec(1, "late", 8, 10, 0.0, 0.0, True, False),
        _rec(2, "early_leave", 8, 10, 20.0, 0.0, False, False),
    ]
    _assert_attendance(data, expected, label="迟到早退分池")


# --------------------------------------------------------------------------
# 场景7：未知侧不能默认0——迟到此前1次已知、早退此前未知。
# 当前 _monthly_entry() 把未提供的 early 默认 0 直接算 → 状态应为 need_more_information 而
# 当前 succeed → 应 RED。只断言状态/category/calculation None/追问，不臆造已解析的部分结果。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_unknown_early_not_default_zero(probes, subject_a) -> None:
    message = "本月此前迟到免扣1次，早退此前免扣几次我不知道，今天迟到8分钟、早退8分钟，各扣多少？"
    data = await bs.request_task(probes, "consult", _consult(subject_a, message))
    _assert_need_exempt(data, label="早退未知不能默认0", ask_token="免")


# --------------------------------------------------------------------------
# 场景8：Golden 多记录——此前两类免扣都2次，迟到65 + 迟到10 分钟。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_golden_multi_records(probes, subject_a) -> None:
    message = "本月此前迟到免扣2次、早退免扣2次，今天迟到65分钟、又迟到10分钟，合计扣多少？"
    data = await bs.request_task(probes, "consult", _consult(subject_a, message))
    expected = [
        _rec(1, "late", 65, None, 0.0, 0.5, False, True),
        _rec(2, "late", 10, 10, 20.0, 0.0, False, False),
    ]
    _assert_attendance(data, expected, label="Golden多记录")


# --------------------------------------------------------------------------
# 场景9：模糊输入——不能猜时长，须判失败并给出精确 error_code。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_vague_duration_failed(probes, subject_a) -> None:
    data = await bs.request_task(probes, "consult", _consult(subject_a, "迟到大概半小时扣多少？"))
    bs._check(data.get("status") == "failed", "模糊时长未判为failed")
    bs._check(
        data.get("error_code") == "insufficient_attendance_duration",
        "模糊时长error_code不精确",
    )
    bs._check(
        data.get("question_category") == "attendance_calculation",
        "模糊时长question_category非attendance_calculation",
    )
    bs._check(data.get("calculation") is None, "模糊时长不应有calculation")
    _assert_truthy(data.get("answer"), label="模糊时长")


# --------------------------------------------------------------------------
# 场景10：制度问题——不得标为 attendance_calculation，calculation 必须 None。
# 真实 Knowledge 结果可能是 succeeded/not_found/temporarily_unavailable，故不冻结状态，
# 不把外部知识命中率作为 WP-04 结论。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_policy_not_calculation(probes, subject_a) -> None:
    data = await bs.request_task(probes, "consult", _consult(subject_a, "公司迟到扣款规定是什么？"))
    bs._check(
        data.get("question_category") != "attendance_calculation",
        "制度问题被误判为考勤计算",
    )
    bs._check(data.get("calculation") is None, "制度问题出现计算证据")
    _assert_truthy(data.get("answer"), label="制度问题")
