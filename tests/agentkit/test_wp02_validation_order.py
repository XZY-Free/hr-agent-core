"""WP-02「Leave 完整输入业务拒绝顺序」远端验收（TESTS ONLY）。

范围：只覆盖 Leave 完整输入的业务拒绝顺序不变式——
type normalization → permission → gender → date/schedule/authority → balance/unit，
且每步 fail-closed。四个场景用「后续原因必然失败」的输入证明先序检查先于后序检查：
permission 先于 schedule、gender 先于 schedule/balance、balance 先于 ready/submission。
只读真实 Orchestrator（HTTPS A2A），不 import apps/packages/veadk，无本地应用/模型/服务/
ASGI/mock/skip/xfail，不调用 localhost，不写 env、不写云。

当前 v17 发布事实（来自已发布 stub，本文件不修复/不注入任何业务数据）：
- employee.sex = F。
- 权限含 A08「陪产假」、C01「事假」，但不含 A03「婚假」。
- 2026-10-18 为 UNKNOWN 排班；2026-10-12 为 WORK 08:00–17:00。
- C01 事假当前无任何余额行。
标准名/typeCode（不从业务包 import，按 packages/hr_domain/constants/leave_rules.py
代码阅读填入固定公开 code）：婚假=A03、陪产假=A08、丧假=A04、事假=C01。

未来发布事实（由 ROOT 在对应实现发布时注入；本文件只依赖其满足时可观察结果，不写 env）：
- 权限加入 A04「丧假」（无 A04 余额行）。
- C01 事假余额行 leaveRemain=5/leaveTotal=5/leaveUsed=0/effectiveYear=2026，
  但故意省略 leaveUnit（用于「单位未知」fail-closed，不许默认 day）。

冻结行为（目标契约；线上已满足即绿，无需实现阶段）：
1. 「2026年10月18日请1天婚假」→ permission(no_permission) 先于 schedule；公共
   input_required；draft validation_failed/代码 no_permission；不得 schedule_unknown；
   无 authority/submission。
2. 「2026年10月18日请1天陪产假」→ gender(gender_mismatch) 先于 schedule 与余额；
   公共 input_required；draft validation_failed/代码 gender_mismatch；无 authority/submission。
3. 「2026年10月12日请1天丧假」→ balance(balance_unknown，无 A04 余额行)；公共
   input_required；draft validation_failed/代码 balance_unknown；权威保留
   10/12..10/12 08:00–17:00 / 1 day；不得 ready/submission。
4. 「2026年10月12日请1天事假」→ balance_unit_unknown（余额数值存在但单位缺失，不得默认
   day）；公共 input_required；draft validation_failed/代码 balance_unit_unknown；权威保留
   1 day；不得 insufficient_balance/success/submission。

安全：所有断言走 business_support._check()，避免 pytest 断言内省打印主体 / oracle /
原始响应正文；不打印凭据 / env / ref。HTTP 401/500/timeout 与未知协议错误一律视为失败，
绝不当作预期业务拒绝。当前 v17 前两个应通过；后两个因未来 fixture 未发布而真实 RED，
不要强求全部 RED。
"""

from __future__ import annotations

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 排班事实：2026-10-18 UNKNOWN，2026-10-12 WORK 08:00–17:00。
DATE_UNKNOWN = "2026-10-18"
DATE_WORK = "2026-10-12"
WORK_START = "08:00"
WORK_END = "17:00"

# 标准名 / typeCode / 来源（不 import 业务包，固定公开 code）。
TYPE_MARRIAGE = ("婚假", "A03")
TYPE_PATERNITY = ("陪产假", "A08")
TYPE_BEREAVEMENT = ("丧假", "A04")
TYPE_PERSONAL = ("事假", "C01")
TYPE_SOURCE = "normalized_user"

# 固定校验错误码（与领域规则字符串一致）。
NO_PERMISSION = "no_permission"
GENDER_MISMATCH = "gender_mismatch"
BALANCE_UNKNOWN = "balance_unknown"
BALANCE_UNIT_UNKNOWN = "balance_unit_unknown"
SCHEDULE_UNKNOWN = "schedule_unknown"
INSUFFICIENT_BALANCE = "insufficient_balance"

_TERMINAL_OR_CONFIRMED = frozenset({"confirmed", "terminal"})


# --------------------------------------------------------------------------
# fixtures（与已有 WP02 沿用完全相同；task_id 由 support 自动唯一）
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


def _assert_type(draft: dict, name: str, code: str, *, label: str) -> None:
    bs._check(draft.get("normalized_type_name") == name,
              f"{label}标准假名不是 {name}")
    bs._check(draft.get("type_code") == code, f"{label}type_code 不是 {code}")
    bs._check(draft.get("type_source") == TYPE_SOURCE,
              f"{label}类型来源未追溯到用户")


def _assert_validation_failed(draft: dict, *, label: str) -> None:
    status = _status_of(draft, label=label)
    bs._check(status == "validation_failed", f"{label}草稿状态不是 validation_failed")
    bs._check(status not in _TERMINAL_OR_CONFIRMED, f"{label}不应进入 confirmed/terminal")


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


def _assert_no_authority(draft: dict, *, label: str) -> None:
    """permission/gender 拒绝发生在排班前，权威字段必须为空（fail-closed）。"""
    bs._check(draft.get("authoritative_start_date") is None,
              f"{label}拒绝前不应有权威起始日期")
    bs._check(draft.get("authoritative_end_date") is None,
              f"{label}拒绝前不应有权威结束日期")
    bs._check(draft.get("authoritative_duration_value") is None,
              f"{label}拒绝前不应有权威时长值")
    bs._check(draft.get("authoritative_duration_unit") is None,
              f"{label}拒绝前不应有权威时长单位")


def _assert_one_day_authority(draft: dict, *, label: str) -> None:
    """排班+规则已产出权威 1 day：10/12..10/12 08:00–17:00。"""
    bs._check(draft.get("authoritative_start_date") == DATE_WORK,
              f"{label}权威起始日期与期望不一致")
    bs._check(draft.get("authoritative_end_date") == DATE_WORK,
              f"{label}权威结束日期与期望不一致")
    bs._check(draft.get("authoritative_start_time") == WORK_START,
              f"{label}权威开始时间与期望不一致")
    bs._check(draft.get("authoritative_end_time") == WORK_END,
              f"{label}权威结束时间与期望不一致")
    bs._check(draft.get("authoritative_duration_value") == 1,
              f"{label}权威时长应为 1")
    bs._check(draft.get("authoritative_duration_unit") == "day",
              f"{label}权威时长单位应为 day")


# --------------------------------------------------------------------------
# 1) 2026年10月18日请1天婚假 → no_permission 先于 schedule
#    即便日期排班 UNKNOWN，也必须 permission 失败；不得 schedule_unknown、无 authority/submission。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_marriage_no_permission_before_schedule(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        f"我要请{DATE_UNKNOWN}起1天婚假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="婚假无权限")
    draft = bs.public_draft(data, label="婚假无权限")
    _assert_validation_failed(draft, label="婚假无权限")
    _assert_type(draft, TYPE_MARRIAGE[0], TYPE_MARRIAGE[1], label="婚假无权限")
    _draft_id_of(draft, label="婚假无权限")
    _revision_of(draft, label="婚假无权限")
    # permission 先于 schedule：10/18 虽然排班 UNKNOWN，也必须是 no_permission。
    code = _validation_error_code(data, label="婚假无权限")
    bs._check(code == NO_PERMISSION, f"婚假无权限校验码非 {NO_PERMISSION}")
    bs._check(code != SCHEDULE_UNKNOWN, "婚假无权限不应为 schedule_unknown")
    _assert_no_authority(draft, label="婚假无权限")
    _assert_no_success_submission(data, label="婚假无权限")
    _assert_answer_business_failure(_answer_of(data, label="婚假无权限"), data,
                                    label="婚假无权限")


# --------------------------------------------------------------------------
# 2) 2026年10月18日请1天陪产假 → gender_mismatch 先于 schedule 与余额
#    A08 虽有权限，但员工 F 而陪产假限 M；即便排班 UNKNOWN / A08 金额单位存疑，也必 gender_mismatch。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_paternity_gender_mismatch_before_schedule_and_balance(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        f"我要请{DATE_UNKNOWN}起1天陪产假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="陪产假性别不符")
    draft = bs.public_draft(data, label="陪产假性别不符")
    _assert_validation_failed(draft, label="陪产假性别不符")
    _assert_type(draft, TYPE_PATERNITY[0], TYPE_PATERNITY[1], label="陪产假性别不符")
    _draft_id_of(draft, label="陪产假性别不符")
    _revision_of(draft, label="陪产假性别不符")
    bs._check(_validation_error_code(data, label="陪产假性别不符") == GENDER_MISMATCH,
              "陪产假性别不符校验码非 gender_mismatch")
    _assert_no_authority(draft, label="陪产假性别不符")
    _assert_no_success_submission(data, label="陪产假性别不符")
    _assert_answer_business_failure(_answer_of(data, label="陪产假性别不符"), data,
                                    label="陪产假性别不符")


# --------------------------------------------------------------------------
# 3) 2026年10月12日请1天丧假 → balance_unknown（无 A04 余额行）
#    permission/性别/排班均通过、权威 1 day 已计算；无 A04 余额行 → balance_unknown，
#    不得 ready/submission，权威保留。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_bereavement_balance_unknown_keeps_authority_no_submission(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        f"我要请{DATE_WORK}起1天丧假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="丧假无余额")
    draft = bs.public_draft(data, label="丧假无余额")
    _assert_validation_failed(draft, label="丧假无余额")
    _assert_type(draft, TYPE_BEREAVEMENT[0], TYPE_BEREAVEMENT[1], label="丧假无余额")
    _draft_id_of(draft, label="丧假无余额")
    _revision_of(draft, label="丧假无余额")
    bs._check(_validation_error_code(data, label="丧假无余额") == BALANCE_UNKNOWN,
              "丧假无余额校验码非 balance_unknown")
    _assert_one_day_authority(draft, label="丧假无余额")
    _assert_no_success_submission(data, label="丧假无余额")
    _assert_answer_business_failure(_answer_of(data, label="丧假无余额"), data,
                                    label="丧假无余额")


# --------------------------------------------------------------------------
# 4) 2026年10月12日请1天事假 → balance_unit_unknown（数值存在但单位缺失，不默认 day）
#    权限/性别/排班均通过、权威 1 day 已计算；C01 余额行缺 leaveUnit → balance_unit_unknown，
#    不得默认 day、不得 insufficient_balance/success/submission，权威保留。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_personal_balance_unit_unknown_no_default_day(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        f"我要请{DATE_WORK}起1天事假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="事假单位未知")
    draft = bs.public_draft(data, label="事假单位未知")
    _assert_validation_failed(draft, label="事假单位未知")
    _assert_type(draft, TYPE_PERSONAL[0], TYPE_PERSONAL[1], label="事假单位未知")
    _draft_id_of(draft, label="事假单位未知")
    _revision_of(draft, label="事假单位未知")
    code = _validation_error_code(data, label="事假单位未知")
    bs._check(code == BALANCE_UNIT_UNKNOWN, "事假单位未知校验码非 balance_unit_unknown")
    bs._check(code != INSUFFICIENT_BALANCE, "事假单位未知不应为 insufficient_balance")
    _assert_one_day_authority(draft, label="事假单位未知")
    _assert_no_success_submission(data, label="事假单位未知")
    _assert_answer_business_failure(_answer_of(data, label="事假单位未知"), data,
                                    label="事假单位未知")
