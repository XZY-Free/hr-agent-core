"""WP-02「排班三态与连续/跳休日期语义」远端验收（TESTS ONLY）。

范围：只覆盖单一业务不变量——Leave 规则必须把排班明确区分 WORK / REST / UNKNOWN，
并按「连续自然日假」与「跳休假」采用不同的确定性日期语义；旧的 `>27 天 → shrink_workday`
技术分支不得存在。只读真实已部署 Orchestrator（HTTPS A2A），不 import apps/packages/veadk；
无本地应用/模型/服务/ASGI/mock/monkeypatch/skip/xfail；不调用 localhost，不写环境，
不读写云/secret。复用 business_support 的 identity oracle / probes / request_task /
public_draft / public_data / _check，所有断言走 bs._check。

发布事实（来自已发布 stub 与 ROOT 已读生产代码，本文件不修复/不注入任何业务数据；
ROOT 会在对应实现发布时给服务端显式 Gaia stub 增加固定合成排班，测试自身绝不经环境写入）：
- 病假标准名「病假」、code=B01（packages/hr_domain/constants/leave_rules.py，测试不
  import 业务包，从代码阅读填入固定公开 code）；病假 SKIP_RESTDAY_MAP=True → 连续自然日。
- 年休假标准名「年休假」、code=A31；年休假 SKIP_RESTDAY_MAP=False → 跳休（按排班跳过休息日）。
- schedule_overrides（未来 fixture）：2026-10-24=OFF01 休息 00:00-00:00；2026-10-25=OFF01；
  2026-10-18=未知记录（shiftCode/startTime/endTime 均空字符串）。其它相关日期按默认
  WORK 08:00-17:00。
- leave_balance 追加病假 B01（future fixture）：leaveUnit=day、leaveRemain=10、
  leaveTotal=10、leaveUsed=0、effectiveYear=2026。权限已有 A31 年休假、B01 病假；
  年休假余额 4 day。

当前 v15 RED 原因（真实生产缺电，不制造其它失败）：
- 当前发布 v15 尚无上述 schedule_overrides（2026-10-18 未知记录、2026-10-24/10-25 未标
  OFF01），也无病假 B01 余额行（leaveUnit=day、leaveRemain=10）。故目标场景均真实 RED。
- 连续自然日遇 REST 的 canonical 时段为 08:00-18:00（领域常量，见工程包 §10）；UNKNOWN
  一律 fail-closed、绝不跳过。98 天用例区间 10-23..2027-01-28 已不含 UNKNOWN（UNKNOWN 移到
  10-18，在该区间外），故它走完整排班证据后在余额不足处返回 insufficient_balance。本文件绝不
  把这些 RED 归因于 schedule_unknown / horizon，也不把 end 缩短。

冻结行为（目标契约，未追认前均预期 RED）：
1. 「2026年10月24日请1天病假」→ 首日明确 REST 仍允许（连续自然日）→ ready_for_confirmation；
   权威 start_date=10-24、end_date=10-24、08:00-18:00、1 day。
2. 「2026年10月24日请1天年休假」→ 单日跳休落在明确休息日 → validation_failed / rest_day；
   无权威时长/提交，不能自动挪到 10-26。
3. 「从2026年10月24日开始请2天年休假」→ 首日/次日 REST → 权威 start=10-26、end=10-27、
   2 day，ready。
4. 「从2026年10月23日开始请2天年休假」→ 10-23 工作 + 24/25 休息 + 10-26 工作 →
   权威 start=10-23、end=10-26、2 day，ready。
5. 「2026年10月18日请1天年休假」→ UNKNOWN 不能当工作日或休息日 →
   validation_failed / schedule_unknown；无 authority/submission。
6. 「2026年10月17日和2026年10月19日请2天年休假」→ gap 10-18 UNKNOWN →
   validation_failed / schedule_unknown_for_continuity；必须保留两个 requested_date_segments
   （10-17、10-19），不得判连续或 discontinuous_workday_gap。
7. 「从2026年10月23日开始请3天病假」→ 连续自然日跨休息日 → ready；权威 start=10-23、
   end=10-25、08:00-18:00、3 day（24/25 REST 仍计入）。
8. 「从2026年10月23日开始请98天病假」→ 区间 10-23..2027-01-28 无 UNKNOWN，不触发
   27 天/排班 horizon；权威 start=10-23、
   end=2027-01-28、duration=98 day，然后因病假余额 10 day 返回 validation_failed /
   insufficient_balance；不能 schedule_unknown / schedule_horizon_exceeded，也不能把 end 缩短。

公共顶层约定：ready 与 validation_failed 在等待用户动作时均映射 input_required /
error_code=input_required；所有 ready 的 draft 必须非 confirmed/terminal、missing_fields 空、
submission 空；失败 answer 展示 validation_error.message 且不请求确认。所有场景验证标准
类型/code/source（病假 B01、年休假 A31，type_source=normalized_user）。结构化 draft 优先，
answer 只做投影检查，不从 answer 反推业务事实。

安全：所有断言走 business_support._check()，避免 pytest 断言内省打印主体 / oracle / ref /
原始响应正文 / env / secret；错误信息不含主体 / oracle / ref / env / secret / 原响应。
HTTP 401/500/timeout 与未知协议错误一律视为失败，绝不当作预期业务拒绝（业务拒绝只认
错误码 / status，协议层 -32602 由 bs.request_reject 单独区分；本切片不用该路径）。

本文件为独立新文件，不修改其它 worker 的生产文件或已有测试；本文件只做语法静态检查，
不运行 pytest。
"""

from __future__ import annotations

import re

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 发布事实：类型/编码（不 import 业务包，从代码阅读填入固定公开 code）。
TYPE_SICK = "病假"
CODE_SICK = "B01"
TYPE_ANNUAL = "年休假"
CODE_ANNUAL = "A31"

# 排班三态固定事实：10-23/10-26/10-27 WORK 08:00-17:00；10-24/10-25 REST；
# 10-18 UNKNOWN（shiftCode/startTime/endTime 均空）；其它日期默认 WORK 08:00-17:00。
# 98 天区间 10-23..2027-01-28 不含 UNKNOWN（10-18 在区间外）。
DATE_17 = "2026-10-17"
DATE_18 = "2026-10-18"
DATE_19 = "2026-10-19"
DATE_23 = "2026-10-23"
DATE_24 = "2026-10-24"
DATE_25 = "2026-10-25"
DATE_26 = "2026-10-26"
DATE_27 = "2026-10-27"
DATE_49_END = "2027-01-28"   # 98 天连续自然日 end（10-23 + 97 = 1/28/2027，含首尾 98 天）

# WORK 默认班次 / 连续自然日遇 REST 的 canonical 时段（领域常量 08:00-18:00，工程包 §10）。
WORK_START = "08:00"
WORK_END = "17:00"
NATURAL_DAY_START = "08:00"
NATURAL_DAY_END = "18:00"

# 错误码（与领域规则字符串一致，测试不 import 业务包，从代码阅读填入固定公开 code）。
CODE_REST_DAY = "rest_day"
CODE_SCHEDULE_UNKNOWN = "schedule_unknown"
CODE_SCHEDULE_UNKNOWN_CONT = "schedule_unknown_for_continuity"
CODE_INSUFFICIENT_BALANCE = "insufficient_balance"
CODE_HORIZON = "schedule_horizon_exceeded"

_TERMINAL_OR_CONFIRMED = frozenset({"confirmed", "terminal"})


# --------------------------------------------------------------------------
# fixtures（与已有 WP02 沿用完全相同）
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def identity_oracle() -> dict[str, OracleSubject]:
    # 校验（唯一、双主体、ref 唯一、医疗余额互异）在装入期完成，失败即整体失败。
    return bs.load_identity_oracle()


@pytest.fixture(scope="session")
def subject_a(identity_oracle) -> OracleSubject:
    return list(identity_oracle.values())[0]


def _subject_payload(subject: OracleSubject) -> dict:
    return {"subject_id": subject.subject_id, "subject_kind": subject.subject_kind}


# --------------------------------------------------------------------------
# 复用断言（generic message；不打印主体 / oracle / draft 原始值；全部经 bs._check）
# --------------------------------------------------------------------------
def _assert_public_input_required(data: dict, *, label: str) -> None:
    bs._check(data.get("status") == "input_required",
              f"{label}公共顶层状态未映射为 input_required")
    bs._check(data.get("error_code") == "input_required",
              f"{label}公共顶层未返回 input_required 错误码")


def _status_of(draft: dict, *, label: str) -> str:
    status = draft.get("status")
    bs._check(isinstance(status, str) and status, f"{label}草稿缺失 status")
    return status


def _draft_id_of(draft: dict, *, label: str) -> str:
    draft_id = draft.get("draft_id")
    bs._check(isinstance(draft_id, str) and draft_id, f"{label}草稿 draft_id 为空")
    return draft_id


def _revision_of(draft: dict, *, label: str) -> int:
    # revision 必须是 int 且 > 0；type(...) is int 排除 bool（True 是 int 子类）。
    revision = draft.get("revision")
    bs._check(type(revision) is int and revision > 0,
              f"{label}revision 必须为大于 0 的整数(int)")
    return revision


def _assert_type(draft: dict, *, name: str, code: str, label: str) -> None:
    """必须是指定标准假名/code 且类型来源追溯到用户（normalized_user）。"""
    bs._check(draft.get("normalized_type_name") == name,
              f"{label}标准假名非 {name}")
    bs._check(draft.get("type_code") == code, f"{label}type_code 非 {code}")
    bs._check(draft.get("type_source") == "normalized_user",
              f"{label}类型来源未追溯到用户")


def _assert_draft_dates(draft: dict, *, start: str, end: str, label: str) -> None:
    bs._check(draft.get("authoritative_start_date") == start,
              f"{label}权威起始日期与期望不一致")
    bs._check(draft.get("authoritative_end_date") == end,
              f"{label}权威结束日期与期望不一致")


def _assert_draft_times(draft: dict, *, start: str, end: str, label: str) -> None:
    bs._check(draft.get("authoritative_start_time") == start,
              f"{label}权威开始时间与期望不一致")
    bs._check(draft.get("authoritative_end_time") == end,
              f"{label}权威结束时间与期望不一致")


def _assert_authoritative_duration(draft: dict, *, value, duration_unit: str, label: str) -> None:
    bs._check(draft.get("authoritative_duration_value") == value,
              f"{label}权威时长与期望不一致")
    bs._check(draft.get("authoritative_duration_unit") == duration_unit,
              f"{label}权威时长单位与期望不一致")


def _assert_requested_duration_without_end(draft: dict, *, start: str, label: str) -> None:
    """不变量前提：时长由「工作日/自然日数量」驱动，不得由用户提供结束日期。"""
    bs._check(draft.get("requested_start_date") == start,
              f"{label}requested_start_date 不符")
    bs._check(draft.get("requested_end_date") is None,
              f"{label}必须是无 requested_end_date 的时长请求")
    duration = draft.get("authoritative_duration_value")
    bs._check(type(duration) in (int, float) and duration > 0,
              f"{label}必须由数量驱动的权威时长")


def _missing_fields(data: dict, *, label: str) -> list:
    inner = bs.public_data(data, label=label)
    missing = inner.get("missing_fields")
    bs._check(isinstance(missing, list), f"{label}公共结果未返回 missing_fields 数组")
    return missing


def _assert_missing_empty(data: dict, *, label: str) -> None:
    missing = _missing_fields(data, label=label)
    bs._check(not missing, f"{label}ready 态不应存在缺失槽位")


def _validation_error_code(data: dict, *, label: str) -> str:
    inner = bs.public_data(data, label=label)
    validation = inner.get("validation_error")
    bs._check(isinstance(validation, dict), f"{label}公共结果未返回 validation_error 对象")
    code = validation.get("code")
    bs._check(isinstance(code, str) and code, f"{label}公共结果未返回 validation_error.code")
    return code


def _answer_of(data: dict, *, label: str) -> str:
    answer = data.get("answer")
    bs._check(isinstance(answer, str) and answer, f"{label}公共结果缺少 answer")
    return answer


def _assert_answer_not_confirmation(answer: str, *, label: str) -> None:
    bs._check("确认提交" not in answer and "请核对您的" not in answer,
              f"{label}validation_failed 的 answer 不应请求确认")


def _assert_answer_business_failure(answer: str, data: dict, *, label: str) -> None:
    """校验失败：answer 必须展示对应业务失败（validation_error.message），而非请求确认。"""
    _assert_answer_not_confirmation(answer, label=label)
    inner = bs.public_data(data, label=label)
    validation = inner.get("validation_error")
    bs._check(isinstance(validation, dict), f"{label}未返回 validation_error 对象")
    message = validation.get("message")
    bs._check(isinstance(message, str) and message, f"{label}validation_error.message 为空")
    bs._check(message in answer, f"{label}answer 未展示对应业务失败")


def _answer_day_pattern(value) -> str:
    """边界安全的天数投影正则：接受等值的“1 天”“1.0 天”。

    用负向后顾 (?<![0-9.]) 防止把 11 天误当 1 天、把 10.5 天误当 0.5 天；整数倍同时接受
    “X 天”与“X.0 天”（其间可省略空格）。
    """
    if float(value).is_integer():
        return r"(?<![0-9.])%s(?:\.0)?\s*天" % str(int(value))
    return r"(?<![0-9.])%s\s*天" % f"{value:g}"


def _assert_answer_projection(answer: str, draft: dict, *, label: str) -> None:
    """确认摘要必须投影已校验的权威草稿：日期/时段/时长逐字段一致（只做包含式投影）。"""
    bs._check(draft.get("authoritative_start_date") in answer,
              f"{label}answer 未展示权威起始日期")
    bs._check(draft.get("authoritative_end_date") in answer,
              f"{label}answer 未展示权威结束日期")
    bs._check(draft.get("authoritative_start_time") in answer,
              f"{label}answer 未展示权威开始时间")
    bs._check(draft.get("authoritative_end_time") in answer,
              f"{label}answer 未展示权威结束时间")
    unit = draft.get("authoritative_duration_unit")
    bs._check(unit == "day", f"{label}确认摘要投影前置：权威单位应为 day")
    pattern = _answer_day_pattern(draft.get("authoritative_duration_value"))
    bs._check(re.search(pattern, answer) is not None,
              f"{label}answer 未展示权威天数")


def _assert_no_success_submission(data: dict, *, label: str) -> None:
    inner = bs.public_data(data, label=label)
    bs._check(inner.get("submission") is None, f"{label}不应携带成功 submission")


def _assert_not_confirmable_or_terminal(draft: dict, *, label: str) -> None:
    status = _status_of(draft, label=label)
    bs._check(status == "validation_failed", f"{label}草稿状态不是 validation_failed")
    bs._check(status not in _TERMINAL_OR_CONFIRMED, f"{label}不应进入 confirmed/terminal")


# --------------------------------------------------------------------------
# ready 基线：完整校验全部字段 + missing 空 + submission 空 + answer 投影。
# --------------------------------------------------------------------------
def _require_ready(data: dict, *, label: str, type_name: str, type_code: str,
                   start_date: str, end_date: str, start_time: str, end_time: str,
                   duration_value, requested_start_date: str) -> dict:
    _assert_public_input_required(data, label=label)
    draft = bs.public_draft(data, label=label)
    bs._check(_status_of(draft, label=label) == "ready_for_confirmation",
              f"{label}未进入 ready_for_confirmation")
    bs._check(_status_of(draft, label=label) not in _TERMINAL_OR_CONFIRMED,
              f"{label}不应为 confirmed/terminal")
    _assert_type(draft, name=type_name, code=type_code, label=label)
    _draft_id_of(draft, label=label)
    _revision_of(draft, label=label)
    bs._check(draft.get("requested_start_date") == requested_start_date,
              f"{label}requested_start_date 与期望不一致")
    _assert_draft_dates(draft, start=start_date, end=end_date, label=label)
    _assert_draft_times(draft, start=start_time, end=end_time, label=label)
    _assert_authoritative_duration(draft, value=duration_value, duration_unit="day", label=label)
    bs._check((draft.get("reason") or "") == "", f"{label}理由应为空")
    _assert_missing_empty(data, label=label)
    _assert_no_success_submission(data, label=label)
    _assert_answer_projection(_answer_of(data, label=label), draft, label=label)
    return draft


# --------------------------------------------------------------------------
# 1) 2026-10-24 连续自然日病假：首日明确 REST 仍允许 → ready，10-24..10-24、08:00-18:00、1 day。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_sick_leave_rest_day_start_allowed_ready(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "2026年10月24日请1天病假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft = _require_ready(
        data, label="10-24病假",
        type_name=TYPE_SICK, type_code=CODE_SICK,
        start_date=DATE_24, end_date=DATE_24,
        start_time=NATURAL_DAY_START, end_time=NATURAL_DAY_END,
        duration_value=1, requested_start_date=DATE_24,
    )
    # 连续自然日：首日为 REST 仍计作 1 个自然日，绝不因 REST 拒绝。
    bs._check(draft.get("authoritative_duration_value") == 1,
              "10-24病假权威时长应为 1 天")
    _assert_draft_times(draft, start=NATURAL_DAY_START, end=NATURAL_DAY_END, label="10-24病假")


# --------------------------------------------------------------------------
# 2) 2026-10-24 单日年休假落在明确休息日 → validation_failed / rest_day；
#    不改期、不自动挪到 10-26，无权威时长/提交。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_annual_single_on_rest_day_rejected_rest_day(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "2026年10月24日请1天年休假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="休息日年假")
    draft = bs.public_draft(data, label="休息日年假")
    _assert_not_confirmable_or_terminal(draft, label="休息日年假")
    _assert_type(draft, name=TYPE_ANNUAL, code=CODE_ANNUAL, label="休息日年假")
    _draft_id_of(draft, label="休息日年假")
    _revision_of(draft, label="休息日年假")
    bs._check(draft.get("requested_start_date") == DATE_24,
              "休息日年假 requested_start_date 应为 10-24")
    bs._check(_validation_error_code(data, label="休息日年假") == CODE_REST_DAY,
              "休息日年假校验码非 rest_day")
    # 单日跳休落在休息日：不自动挪到下一个工作日 10-26，也不给权威时长/提交。
    bs._check(draft.get("authoritative_start_date") != DATE_26,
              "休息日年假不应自动挪到 10-26")
    bs._check(draft.get("authoritative_duration_value") is None,
              "休息日年假不应臆造权威时长")
    _assert_no_success_submission(data, label="休息日年假")
    _assert_answer_business_failure(_answer_of(data, label="休息日年假"), data,
                                    label="休息日年假")


# --------------------------------------------------------------------------
# 3) 从 10-24 起请 2 天年休假：首日/次日 REST → 权威 start=10-26、end=10-27、2 day，ready。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_annual_two_days_skip_rest_cross_them_ready(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "从2026年10月24日开始请2天年休假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft = _require_ready(
        data, label="10-24起2天年假",
        type_name=TYPE_ANNUAL, type_code=CODE_ANNUAL,
        start_date=DATE_26, end_date=DATE_27,
        start_time=WORK_START, end_time=WORK_END,
        duration_value=2, requested_start_date=DATE_24,
    )
    # 跳休：10-24/10-25 为 REST，不计工作日，权威起算到下一个工作日 10-26。
    _assert_requested_duration_without_end(draft, start=DATE_24, label="10-24起2天年假")
    bs._check(draft.get("authoritative_start_date") == DATE_26,
              "10-24起2天年假权威起始日期应为 10-26，不能停在休息日")


# --------------------------------------------------------------------------
# 4) 从 10-23 起请 2 天年休假：10-23 工作 + 24/25 休息 + 10-26 工作 →
#    权威 start=10-23、end=10-26、2 day，ready。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_annual_two_days_from_work_cross_rest_then_work_ready(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "从2026年10月23日开始请2天年休假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft = _require_ready(
        data, label="10-23起2天年假",
        type_name=TYPE_ANNUAL, type_code=CODE_ANNUAL,
        start_date=DATE_23, end_date=DATE_26,
        start_time=WORK_START, end_time=WORK_END,
        duration_value=2, requested_start_date=DATE_23,
    )
    _assert_requested_duration_without_end(draft, start=DATE_23, label="10-23起2天年假")
    bs._check(draft.get("authoritative_duration_value") == 2,
              "10-23起2天年假权威时长应为 2 天")
    # 两个工作日 10-23 与 10-26（中间 24/25 休息），权威结束不落在休息日。
    bs._check(draft.get("authoritative_end_date") == DATE_26,
              "10-23起2天年假权威结束日期应为 10-26")


# --------------------------------------------------------------------------
# 5) 2026-10-18 单日年休假（UNKNOWN）→ validation_failed / schedule_unknown；
#    UNKNOWN 不能当工作日或休息日，无 authority/submission。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_annual_unknown_day_schedule_unknown(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "2026年10月18日请1天年休假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="10-18未知排班")
    draft = bs.public_draft(data, label="10-18未知排班")
    _assert_not_confirmable_or_terminal(draft, label="10-18未知排班")
    _assert_type(draft, name=TYPE_ANNUAL, code=CODE_ANNUAL, label="10-18未知排班")
    _draft_id_of(draft, label="10-18未知排班")
    _revision_of(draft, label="10-18未知排班")
    bs._check(draft.get("requested_start_date") == DATE_18,
              "10-18未知排班 requested_start_date 应为 10-18")
    bs._check(_validation_error_code(data, label="10-18未知排班") == CODE_SCHEDULE_UNKNOWN,
              "10-18未知排班校验码非 schedule_unknown")
    # UNKNOWN 不得当作工作日/休息日：既不能 ready（WORK）也不能 rest_day（REST）。
    bs._check(_status_of(draft, label="10-18未知排班") == "validation_failed",
              "10-18未知排班不得判为工作日或休息日")
    bs._check(draft.get("authoritative_duration_value") is None,
              "10-18未知排班不应臆造权威时长")
    _assert_no_success_submission(data, label="10-18未知排班")
    _assert_answer_business_failure(_answer_of(data, label="10-18未知排班"), data,
                                    label="10-18未知排班")


# --------------------------------------------------------------------------
# 6) 离散 10-17 + 10-19（gap 10-18 UNKNOWN）→ validation_failed /
#    schedule_unknown_for_continuity；保留两个 requested_date_segments，不得判连续或
#    discontinuous_workday_gap。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_annual_discrete_gap_unknown_not_continuous(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "2026年10月17日和2026年10月19日请2天年休假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="离散中间未知")
    draft = bs.public_draft(data, label="离散中间未知")
    _assert_not_confirmable_or_terminal(draft, label="离散中间未知")
    _assert_type(draft, name=TYPE_ANNUAL, code=CODE_ANNUAL, label="离散中间未知")
    _draft_id_of(draft, label="离散中间未知")
    _revision_of(draft, label="离散中间未知")

    # 结构化事实优先：模型必须保留两个离散日期段（服务端 data.draft 快照），不从 answer 反推。
    segs = draft.get("requested_date_segments")
    bs._check(isinstance(segs, list) and len(segs) == 2,
              "离散中间未知 requested_date_segments 应为两个日期")
    bs._check(DATE_17 in segs and DATE_19 in segs,
              "离散中间未知 requested_date_segments 缺少期望日期")
    bs._check(DATE_18 not in segs,
              "离散中间未知 requested_date_segments 不应包含中间未知日期 10-18")
    # gap 中的未知排班：不得武断判连续，也不得当作已知工作日间隔。
    bs._check(_validation_error_code(data, label="离散中间未知") == CODE_SCHEDULE_UNKNOWN_CONT,
              "离散中间未知校验码非 schedule_unknown_for_continuity")
    bs._check(_validation_error_code(data, label="离散中间未知") != "discontinuous_workday_gap",
              "离散中间未知不应误判为 discontinuous_workday_gap")
    _assert_no_success_submission(data, label="离散中间未知")
    _assert_answer_business_failure(_answer_of(data, label="离散中间未知"), data,
                                    label="离散中间未知")


# --------------------------------------------------------------------------
# 7) 从 10-23 起请 3 天病假（连续自然日跨休息日）→ ready；权威 start=10-23、
#    end=10-25、08:00-18:00、3 day（24/25 REST 仍计入）。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_sick_leave_three_days_cross_rest_ready(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "从2026年10月23日开始请3天病假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    draft = _require_ready(
        data, label="10-23起3天病假",
        type_name=TYPE_SICK, type_code=CODE_SICK,
        start_date=DATE_23, end_date=DATE_25,
        start_time=WORK_START, end_time=NATURAL_DAY_END,
        duration_value=3, requested_start_date=DATE_23,
    )
    _assert_requested_duration_without_end(draft, start=DATE_23, label="10-23起3天病假")
    # 连续自然日：3 个自然日 = 10-23/24/25，24/25 为 REST 仍计入，权威结束为休息日 canonical 18:00。
    bs._check(draft.get("authoritative_end_date") == DATE_25,
              "10-23起3天病假权威结束日期应为 10-25")
    bs._check(draft.get("authoritative_duration_value") == 3,
              "10-23起3天病假权威时长应为 3 天")
    bs._check(draft.get("authoritative_end_time") == NATURAL_DAY_END,
              "10-23起3天病假权威结束时间为休息日 canonical 18:00")


# --------------------------------------------------------------------------
# 8) 从 10-23 起请 98 天病假：不触发 27 天/排班 horizon；权威 start=10-23、
#    end=2027-01-28、duration=98 day，然后因病假余额 10 day 返回 validation_failed /
#    insufficient_balance；不能 schedule_unknown/schedule_horizon_exceeded，也不能缩短 end。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_sick_leave_98_days_insufficient_not_horizon(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "从2026年10月23日开始请98天病假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="98天病假")
    draft = bs.public_draft(data, label="98天病假")
    _assert_not_confirmable_or_terminal(draft, label="98天病假")
    _assert_type(draft, name=TYPE_SICK, code=CODE_SICK, label="98天病假")
    _draft_id_of(draft, label="98天病假")
    _revision_of(draft, label="98天病假")
    _assert_requested_duration_without_end(draft, start=DATE_23, label="98天病假")

    # 连续自然日 98 天：start=10-23、end=2027-01-28、98 day（不含 >27 天 shrink 分支）。
    _assert_draft_dates(draft, start=DATE_23, end=DATE_49_END, label="98天病假")
    _assert_authoritative_duration(draft, value=98, duration_unit="day", label="98天病假")
    bs._check(draft.get("authoritative_end_date") == DATE_49_END,
              "98天病假权威结束日期应为 2027-01-28，不能缩短")

    # 余额检查：病假余额 10 day → insufficient_balance；绝不可 schedule_unknown / horizon。
    code = _validation_error_code(data, label="98天病假")
    bs._check(code == CODE_INSUFFICIENT_BALANCE,
              "98天病假校验码非 insufficient_balance")
    bs._check(code != CODE_SCHEDULE_UNKNOWN,
              "98天病假不应为 schedule_unknown")
    bs._check(code != CODE_HORIZON,
              "98天病假不应为 schedule_horizon_exceeded")
    bs._check(_status_of(draft, label="98天病假") != "ready_for_confirmation",
              "98天病假不应进入 ready_for_confirmation")
    _assert_no_success_submission(data, label="98天病假")
    _assert_answer_business_failure(_answer_of(data, label="98天病假"), data,
                                    label="98天病假")
