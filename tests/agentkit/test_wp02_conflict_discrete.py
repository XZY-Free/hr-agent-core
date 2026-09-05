"""WP-02「Leave Draft 归一化与连续性拒绝」远端验收（TESTS ONLY）。

范围：只覆盖两条相邻的 Leave Draft 拒绝规则——
(1) 一次请求包含两个不同假期类型（type_conflict）；
(2) 离散日期段中间夹一个未申请的已知工作日（discontinuous_workday_gap）。
只读真实 Orchestrator（HTTPS A2A），不 import apps/packages/veadk，
无本地应用/模型/服务/ASGI/mock/skip/xfail，不调用 localhost。

当前 v13 发布事实（来自已发布 stub，本文件不修复/不注入任何业务数据）：
- 年休假标准名「年休假」、code=A31（packages/hr_domain/constants/leave_rules.py；
  测试不 import 业务包，从代码阅读填入固定公开 code）；「病假」为已知假期名。
- 2026-10-12 / 2026-10-13 / 2026-10-14 为 stub 明确返回 WORK 08:00–17:00 的日期。
- 工作流规则：一次申请只能包含一个假期类型（type_conflict）；离散日期段之间若出现
  已知工作日即 discontinuous_workday_gap（中间排班未知则 schedule_unknown_for_continuity）。

冻结行为（目标契约；若当前 v13 已满足，ROOT 云端运行本文件应直接绿，无需实现阶段）：
1. 「我要请2026年10月12日一天年假和病假」→ 公共 input_required；data.draft.status=
   validation_failed；validation_error.code=type_conflict；不得 ready/confirmed/terminal、
   不得携带成功 submission；answer 展示 validation_error.message 且不请求确认。
2. 「我想请年假，日期是2026年10月12日和2026年10月14日，共2天」→ 模型必须保留
   requested_date_segments=[2026-10-12, 2026-10-14]；中间 10/13 未申请且为工作日 →
   公共 input_required；draft validation_failed；validation_error.code=
   discontinuous_workday_gap；不得退化成 10/12..10/14 连续三天、不得 ready/terminal/submission。
   只断言结构化字段（data.draft / validation_error / status），不从 answer 反推。

安全：所有断言走 business_support._check()，避免 pytest 断言内省打印主体 / oracle /
原始响应正文；不打印凭据 / env / ref。HTTP 401/500/timeout 与未知协议错误一律视为失败，
绝不当作预期业务拒绝。不追求形式 RED；若线上已满足即无需生产修改。
"""

from __future__ import annotations

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 发布事实：类型/编码（不 import 业务包，从代码阅读填入固定公开 code）。
TYPE_STANDARD = "年休假"
TYPE_CODE = "A31"
# 2026-10-12 / 10-13 / 10-14 均为 stub 明确返回 WORK 08:00–17:00 的日期。
SEG_1 = "2026-10-12"
GAP_DATE = "2026-10-13"
SEG_2 = "2026-10-14"

# 固定错误码，与领域规则字符串一致。
CODE_TYPE_CONFLICT = "type_conflict"
CODE_DISCONTINUOUS = "discontinuous_workday_gap"

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


def _assert_type_annual(draft: dict, *, label: str) -> None:
    """必须是「年休假 / A31」且来源追溯到用户（跳休类，不得被别化）。"""
    bs._check(draft.get("normalized_type_name") == TYPE_STANDARD,
              f"{label}标准假名非 年休假")
    bs._check(draft.get("type_code") == TYPE_CODE, f"{label}type_code 非 A31")
    bs._check(draft.get("type_source") == "normalized_user",
              f"{label}类型来源未追溯到用户")


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


# --------------------------------------------------------------------------
# 1) 一次请求含两个不同假种（年假 + 病假）→ type_conflict；公共 input_required，
#    draft validation_failed；不得 ready/confirmed/terminal、不得带成功 submission。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_type_conflict_two_types_rejected(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我要请2026年10月12日一天年假和病假",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="多假种冲突")
    draft = bs.public_draft(data, label="多假种冲突")
    bs._check(_status_of(draft, label="多假种冲突") == "validation_failed",
              "多假种冲突草稿状态不是 validation_failed")
    bs._check(_status_of(draft, label="多假种冲突") not in _TERMINAL_OR_CONFIRMED,
              "多假种冲突不应进入 confirmed/terminal")
    _draft_id_of(draft, label="多假种冲突")
    bs._check(_validation_error_code(data, label="多假种冲突") == CODE_TYPE_CONFLICT,
              "多假种冲突校验码非 type_conflict")
    _assert_answer_business_failure(_answer_of(data, label="多假种冲突"),
                                    data, label="多假种冲突")
    _assert_no_success_submission(data, label="多假种冲突")


# --------------------------------------------------------------------------
# 2) 离散日期段 10/12 + 10/14（共 2 天），中间 10/13 为未申请工作日 →
#    discontinuous_workday_gap；模型保留 requested_date_segments 为这两个日期，
#    不得退化成 10/12..10/14 连续三天；公共 input_required；不得 ready/terminal/submission。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_discrete_segments_middle_workday_gap_rejected(probes, subject_a) -> None:
    message = bs.orchestrator_message(
        "我想请年假，日期是2026年10月12日和2026年10月14日，共2天",
        execution_subject=_subject_payload(subject_a),
    )
    data = await bs.request_task(probes, "orchestrator", message)
    _assert_public_input_required(data, label="离散中间工作日")
    draft = bs.public_draft(data, label="离散中间工作日")
    bs._check(_status_of(draft, label="离散中间工作日") == "validation_failed",
              "离散中间工作日草稿状态不是 validation_failed")
    bs._check(_status_of(draft, label="离散中间工作日") not in _TERMINAL_OR_CONFIRMED,
              "离散中间工作日不应进入 confirmed/terminal")
    _assert_type_annual(draft, label="离散中间工作日")
    _draft_id_of(draft, label="离散中间工作日")
    _revision_of(draft, label="离散中间工作日")

    # 结构化事实优先：模型必须保留两个离散日期段（服务端 data.draft 快照），不从 answer 反推。
    bs._check(draft.get("requested_start_date") == SEG_1,
              "离散中间工作日 requested_start_date 与期望不一致")
    segs = draft.get("requested_date_segments")
    bs._check(isinstance(segs, list) and len(segs) == 2,
              "离散中间工作日 requested_date_segments 应为两个日期")
    bs._check(SEG_1 in segs and SEG_2 in segs,
              "离散中间工作日 requested_date_segments 缺少期望日期")
    bs._check(GAP_DATE not in segs,
              "离散中间工作日 requested_date_segments 不应包含中间工作日 10/13")
    # 不得退化成 10/12..10/14 连续三天权威，也不得有 3 天权威时长。
    bs._check(draft.get("authoritative_start_date") != SEG_1,
              "离散中间工作日不应写入 10/12 起连续全天权威")
    bs._check(draft.get("authoritative_duration_value") != 3,
              "离散中间工作日不应退化成 3 天权威时长")

    bs._check(_validation_error_code(data, label="离散中间工作日") == CODE_DISCONTINUOUS,
              "离散中间工作日校验码非 discontinuous_workday_gap")
    _assert_answer_business_failure(_answer_of(data, label="离散中间工作日"),
                                    data, label="离散中间工作日")
    _assert_no_success_submission(data, label="离散中间工作日")
