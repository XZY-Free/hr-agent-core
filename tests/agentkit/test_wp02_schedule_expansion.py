"""WP-02「跳休扩窗与 366 上限」远端验收（TESTS ONLY）。

范围：只覆盖「跳休类请假必须由所需工作日数量驱动排班向后扩窗，最多搜索 366 个自然日」
这一单一业务不变量。只读真实 Orchestrator（HTTPS A2A），不 import apps/packages/veadk，
无本地应用/模型/服务/ASGI/mock/skip/xfail，不调用 localhost。

发布事实（来自已发布 stub 与 ROOT 已读生产代码，本文件不修复/不注入任何业务数据）：
- 年休假标准名「年休假」、code=A31（packages/hr_domain/constants/leave_rules.py，
  测试不 import 业务包，从代码阅读填入固定公开 code）。
  SKIP_RESTDAY_MAP["年休假"]=False → 年休假是「跳休」类（按排班跳过休息日累计工作日）。
- 2026-10-19 为 stub 明确返回 WORK 08:00–17:00 的日期；除配置的休息日/UNKNOWN 外，任意请求
  日期均返回 WORK 08:00–17:00。
- 当前发布 Gaia 权限含 A31（年休假），余额行 leaveUnit=day、leaveRemain=4。

当前 v12 RED 原因（真实生产缺电，不制造其它失败）：
- 生产 _schedule_table_for 对没有 requested_end_date 的时长请求只查 requested_start_date
  到 start+30（含首尾 31 天），然后 _duration_plan_skip 遇第 32 天 UNKNOWN 即 schedule_unknown。
  故「2026-10-19 起请 35 天年休假」在尚未扩窗到 35 个工作日本体就 RED 为 schedule_unknown，
  而不是余额不足；「请 367 天」在 v12 同样受 31 天固定窗口限制而 RED 为 schedule_unknown，
  而不是 schedule_horizon_exceeded。

冻结行为（目标契约，未追认前当前 v12 预期 RED）：
1. 从 2026-10-19 起请 35 天年休假、不提供 requested_end_date → 领域必须继续向后拉取排班，
   权威 start=2026-10-19、end=2026-11-24、duration=35 day；因余额只有 4 day，最终
   validation_failed / validation_error.code=insufficient_balance，绝不 schedule_unknown /
   schedule_horizon_exceeded，也不 ready/terminal；公共顶层仍 input_required；answer 展示
   业务失败且不请求确认；不携带成功 submission。
2. 从 2026-10-19 起请 367 天年休假 → validation_failed / validation_error.code=
   schedule_horizon_exceeded（搜索上限先于余额）；不得进入余额不足、不得生成可确认/终态、
   不得有成功 submission。

可增加恰好 366 天边界用例，但它会触发余额不足且耗时较高；本测试刻意不加，保持小而强。
模型自然语言存在变化，但公共 data.draft 是服务端结构化事实；本测试只断言结构化事实，
不在从 answer 反推日期/时长/错误码。

安全：所有断言走 business_support._check()，避免 pytest 断言内省打印主体 / oracle /
原始响应正文 / 身份 / secret；不打印凭据 / env / ref。HTTP 401/500/timeout 与未知协议
错误一律视为失败，绝不当作预期业务拒绝。只断言公共结构（data.draft / validation_error /
status / answer），不从 answer 反推业务事实。
"""

from __future__ import annotations

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 发布事实：类型/编码（不 import 业务包，从代码阅读填入固定公开 code）。
TYPE_STANDARD = "年休假"
CODE_ANNUAL = "A31"
# 2026-10-19 是位于专用 UNKNOWN fixture 之后的明确 WORK 日期。
START_DATE = "2026-10-19"
# 权威源约束：日期权威源只允许 normalized_user/schedule/rule，不允许 user/system。
_DATE_SOURCE_ALLOWED = ("normalized_user", "schedule", "rule")

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


def _assert_type_annual(draft: dict, *, label: str) -> None:
    """必须是「年休假 / A31」且来源追溯到用户（跳休类，不得被别化）。"""
    bs._check(draft.get("normalized_type_name") == TYPE_STANDARD,
              f"{label}标准假名非 年休假")
    bs._check(draft.get("type_code") == CODE_ANNUAL, f"{label}type_code 非 A31")
    bs._check(draft.get("type_source") == "normalized_user",
              f"{label}类型来源未追溯到用户")


def _assert_draft_dates(draft: dict, *, start: str, end: str, label: str) -> None:
    bs._check(draft.get("authoritative_start_date") == start,
              f"{label}权威起始日期与期望不一致")
    bs._check(draft.get("authoritative_end_date") == end,
              f"{label}权威结束日期与期望不一致")


def _assert_authoritative_duration(draft: dict, *, value, duration_unit: str, label: str) -> None:
    bs._check(draft.get("authoritative_duration_value") == value,
              f"{label}权威时长与期望不一致")
    bs._check(draft.get("authoritative_duration_unit") == duration_unit,
              f"{label}权威时长单位与期望不一致")


def _assert_date_sources(draft: dict, *, label: str) -> None:
    # 日期权威源精确契约：只允许 normalized_user/schedule/rule，不允许 user/system。
    start_src = draft.get("authoritative_start_date_source")
    end_src = draft.get("authoritative_end_date_source")
    bs._check(start_src in _DATE_SOURCE_ALLOWED, f"{label}权威起始日期来源非法")
    bs._check(end_src in _DATE_SOURCE_ALLOWED, f"{label}权威结束日期来源非法")


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


def _assert_answer_business_failure(answer: str, data: dict, *, label: str) -> None:
    """校验失败：answer 必须展示对应业务失败（validation_error.message），而非请求确认。"""
    bs._check("确认提交" not in answer and "请核对您的" not in answer,
              f"{label}validation_failed 的 answer 不应请求确认")
    inner = bs.public_data(data, label=label)
    validation = inner.get("validation_error")
    bs._check(isinstance(validation, dict), f"{label}未返回 validation_error 对象")
    message = validation.get("message")
    bs._check(isinstance(message, str) and message, f"{label}validation_error.message 为空")
    bs._check(message in answer, f"{label}answer 未展示对应业务失败")


def _assert_no_success_submission(data: dict, *, label: str) -> None:
    inner = bs.public_data(data, label=label)
    bs._check(inner.get("submission") is None, f"{label}失败不应携带成功 submission")


def _assert_duration_request_without_end(draft: dict, *, label: str) -> None:
    """不变量前提：请求必须以「工作日数量」驱动，不得由用户提供结束日期。"""
    bs._check(draft.get("requested_start_date") == START_DATE,
              f"{label}requested_start_date 不符")
    bs._check(draft.get("requested_end_date") is None,
              f"{label}必须是无 requested_end_date 的时长请求，才能验证扩窗由工作日数量驱动")


# --------------------------------------------------------------------------
# 1) 2026-10-19 起请 35 天年休假（无 requested_end_date）→ 领域继续向后扩窗，
#    权威 end=2026-11-24 / 35 day；因余额 4 day，最终 insufficient_balance，绝不可
#    schedule_unknown / schedule_horizon_exceeded，也不可确认/终态。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_skip_35_days_expands_window_then_insufficient_balance(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月19日起35天年休假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="跳休35天")
    draft = bs.public_draft(data, label="跳休35天")
    bs._check(_status_of(draft, label="跳休35天") == "validation_failed",
              "跳休35天草稿状态不是 validation_failed")
    bs._check(_status_of(draft, label="跳休35天") not in _TERMINAL_OR_CONFIRMED,
              "跳休35天不应进入 confirmed/terminal")
    _assert_type_annual(draft, label="跳休35天")
    _draft_id_of(draft, label="跳休35天")
    _revision_of(draft, label="跳休35天")
    _assert_duration_request_without_end(draft, label="跳休35天")
    bs._check(_validation_error_code(data, label="跳休35天") == "insufficient_balance",
              "跳休35天应因余额不足，而非 schedule_unknown / 上限")
    _assert_draft_dates(draft, start=START_DATE, end="2026-11-24", label="跳休35天")
    _assert_authoritative_duration(draft, value=35, duration_unit="day", label="跳休35天")
    _assert_date_sources(draft, label="跳休35天")
    _assert_answer_business_failure(_answer_of(data, label="跳休35天"), data, label="跳休35天")
    _assert_no_success_submission(data, label="跳休35天")


# --------------------------------------------------------------------------
# 2) 2026-10-19 起请 367 天年休假 → validation_failed / schedule_horizon_exceeded
#    （搜索上限 366 先于余额）；不进入余额不足、不成可确认/终态、无成功 submission。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_skip_367_days_horizon_exceeded(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月19日起367天年休假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="跳休367天")
    draft = bs.public_draft(data, label="跳休367天")
    bs._check(_status_of(draft, label="跳休367天") == "validation_failed",
              "跳休367天草稿状态不是 validation_failed")
    bs._check(_status_of(draft, label="跳休367天") not in _TERMINAL_OR_CONFIRMED,
              "跳休367天不应进入 confirmed/terminal")
    _assert_type_annual(draft, label="跳休367天")
    _draft_id_of(draft, label="跳休367天")
    _revision_of(draft, label="跳休367天")
    _assert_duration_request_without_end(draft, label="跳休367天")
    # 搜索上限先于余额：必须是 schedule_horizon_exceeded，绝不可进入余额不足。
    bs._check(_validation_error_code(data, label="跳休367天") == "schedule_horizon_exceeded",
              "跳休367天校验码非 schedule_horizon_exceeded")
    bs._check(_validation_error_code(data, label="跳休367天") != "insufficient_balance",
              "跳休367天不应进入余额不足")
    _assert_answer_business_failure(_answer_of(data, label="跳休367天"), data, label="跳休367天")
    _assert_no_success_submission(data, label="跳休367天")
