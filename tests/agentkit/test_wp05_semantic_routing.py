"""WP-05 生产模型语义路由云端验收：100 条普通自然语言必须由结构化语义分类器路由。

这不是 keyword/regex 测试。每条自然语言表达都不转成本地分类器 oracle；期望 target 由
「测试数据表本身」决定：leave_transaction / employee_self_data / hr_consultation /
attendance_calculation / needs_clarification 五类各 20 条。路由证据只用公共可观察的
结构化 data.route_target（固定三值契约：local / consult / employee_data，由 Orchestrator
根据实际选中的 RouteTarget/RemoteRouteResponse 生成，不让模型或下游自由提供），绝不解析
answer 反推路由，也不依赖特定回答全文、知识正文或业务数值。data 必须是 dict 且
data.route_target 等于期望固定值，作为主路由证据。

范围：真实 HTTPS A2A 调用（AgentKit 开发 Orchestrator 公共端点）。全部通过
business_support.request_task / probes / orchestrator_message。无本地应用 / 模型 / 服务、
无 fake-model、无 ASGI、无 localhost、无 mock / fixture 伪造。身份从
bs.load_identity_oracle() 第一主体取得并构造 execution_subject。

隔离：每个 case 在调用内使用全新 context_id（`wp05-<uuid>`）。这是单轮隔离请求——
不传 task_id，因为 A2A SDK 对「fresh message 携带未登记 task_id」会抛 TaskNotFoundError；
全新 context_id 已按任务隔离，天然避免 continuation 污染。

证据（Orchestrator v26 真实 root model classifier 已修复并启用）：
- 全部 100 条云端测试结果 88 passed / 12 failed。
- 失败复查：「我的探亲假余额」返回 rejected/policy_query_not_allowed，证明已进入
  Employee Data；两条育儿假咨询返回 input_required/no draft，符合 Consult 追问地区；
  一条考勤失败表达立即重跑变 completed/consultation。故用 completed / result_type
  绑死下游终态结论不稳定。
- 当前生产公共结果尚无 data.route_target，因此本文件在 v26 上是稳定 RED（主路由证据
  缺失）；待生产接入 route_target 后转 GREEN。未接线即断言失败，绝不当作下游业务
  completed 的替代证据。

安全：敏感断言全部走 business_support._check()，避免 pytest 断言内省打印主体 / oracle /
响应正文 / answer / 凭据；不 import apps / packages / veadk，不打印凭据 / env / oracle；
不 skip / xfail。所有响应递归检查不含 employee_id / secret / token 字段或子串。

注：与 WP-01..04 的量算 / 员工数据 / 考勤工具无关；本文件只验证「生产结构化语义分类器」
决定 local（Leave / 澄清，含 need_more_information 澄清）/ Consult A2A / Employee Data A2A
的路线，即 route_target ∈ {local, consult, employee_data}。
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 澄清词白名单：只接受其中之一（不解析 answer 推断路由）。
_CLARIFY_TOKENS = ("办理", "余额", "制度", "哪种", "具体", "想了解")
# Leave 草稿的 input_required 可行状态（领域状态，不由自然语言决定）。
_DRAFT_INPUT_REQUIRED_STATUSES = ("collecting", "ready_for_confirmation", "validation_failed")
# Employee/Consult 下游合同可能返回的公共终态；route_target 与这些终态解耦。
_REMOTE_TERMINAL_STATUSES = ("completed", "input_required", "rejected", "failed")
_FORMAT_PREFIX = "wp05"


# --------------------------------------------------------------------------
# fixtures（与 WP-01..04 一致：subject A 为 oracle 第一条主体）
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def identity_oracle() -> dict[str, OracleSubject]:
    # 校验（两条主体、ref 唯一、医疗余额互异）在装入期完成，失败即整体失败。
    return bs.load_identity_oracle()


@pytest.fixture(scope="session")
def subject_a(identity_oracle) -> OracleSubject:
    return list(identity_oracle.values())[0]


def _subject_payload(subject: OracleSubject) -> dict:
    return {"subject_id": subject.subject_id, "subject_kind": subject.subject_kind}


# --------------------------------------------------------------------------
# 远端调用：单轮隔离请求（全新 context_id），不传 task_id。
# --------------------------------------------------------------------------
async def _route(probes, subject: OracleSubject, text: str) -> dict:
    message = bs.orchestrator_message(
        text,
        context_id=f"{_FORMAT_PREFIX}-{uuid4().hex}",
        execution_subject=_subject_payload(subject),
    )
    return await bs.request_task(probes, "orchestrator", message)


# --------------------------------------------------------------------------
# 复用断言（均不打印主体 / oracle / draft 原始值 / answer / 凭据；全部经 bs._check）
# --------------------------------------------------------------------------
def _assert_no_sensitive(obj, *, label: str) -> None:
    """递归断言响应不含 employee_id/secret/token 字段或子串。"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            bs._check(key not in ("employee_id", "secret", "token"), f"{label}泄露敏感字段")
            _assert_no_sensitive(value, label=label)
    elif isinstance(obj, list):
        for value in obj:
            _assert_no_sensitive(value, label=label)
    elif isinstance(obj, str):
        for token in ("employee_id", "secret", "token"):
            bs._check(token not in obj, f"{label}响应含敏感子串")


def _assert_truthy(answer, *, label: str) -> None:
    bs._check(isinstance(answer, str) and answer.strip(), f"{label}answer为空")


def _assert_no_draft(res: dict, *, label: str) -> None:
    """data 若为 dict 则不得出现 draft 快照（Employee/Consult/澄清均无草稿）。"""
    inner = res.get("data")
    if isinstance(inner, dict):
        bs._check("draft" not in inner, f"{label}不应输出草稿快照")


def _assert_route_target(res: dict, expected: str, *, label: str) -> None:
    """主路由证据：data 必须是 dict 且 data.route_target 等于固定三值契约之一。

    route_target 由 Orchestrator 按实际选中 RouteTarget/RemoteRouteResponse 生成，
    是测试的主路由证据，与下游业务是否 completed 完全解耦；缺失即断言失败。
    """
    inner = res.get("data")
    bs._check(isinstance(inner, dict), f"{label}data负载非 dict")
    bs._check(inner.get("route_target") == expected, f"{label}route_target非 {expected}")


def _assert_error_code_legal(res: dict, *, label: str) -> None:
    """error_code 类型合法：None 或非空字符串（不接受其它类型/空串/缺失语义）。"""
    ec = res.get("error_code")
    bs._check(
        ec is None or (isinstance(ec, str) and ec.strip()),
        f"{label}error_code类型非法",
    )


def _assert_leave_route(res: dict, *, label: str) -> None:
    """Leave：input_required + data.route_target=local + data.draft 为 dict 且 status 属收集/确认/校验失败。"""
    bs._check(res.get("status") == "input_required", f"{label}未映射为 input_required")
    bs._check(
        res.get("result_type") == "missing_information",
        f"{label}result_type非 missing_information",
    )
    _assert_route_target(res, "local", label=label)
    inner = res.get("data")
    draft = inner.get("draft")
    bs._check(isinstance(draft, dict), f"{label}data.draft非 dict")
    bs._check(
        draft.get("status") in _DRAFT_INPUT_REQUIRED_STATUSES,
        f"{label}draft.status非收集/确认/校验失败",
    )
    _assert_truthy(res.get("answer"), label=label)
    _assert_no_sensitive(res, label=label)


def _assert_remote_route(res: dict, expected_target: str, *, label: str) -> None:
    """Employee/Consult 远程路由：route_target 固定；终态允许合同四种之一；无 draft。

    约束：status 必须属于 _REMOTE_TERMINAL_STATUSES（不接受缺失/任意字符串），
    error_code 类型合法（None 或非空字符串），answer 非空、无 draft、无敏感数据；
    绝不解析 answer 推断路由，也不看 result_type 判断 target。
    """
    status = res.get("status")
    bs._check(status in _REMOTE_TERMINAL_STATUSES, f"{label}status缺失或非允许终态")
    _assert_route_target(res, expected_target, label=label)
    _assert_error_code_legal(res, label=label)
    _assert_no_draft(res, label=label)
    _assert_truthy(res.get("answer"), label=label)
    _assert_no_sensitive(res, label=label)


def _assert_employee_route(res: dict, *, label: str) -> None:
    """Employee Data：route_target=employee_data；终态允许四种之一；无 draft。"""
    _assert_remote_route(res, "employee_data", label=label)


def _assert_consult_route(res: dict, *, label: str) -> None:
    """Consult（制度/政策/考勤计算）：route_target=consult；终态允许四种之一；无 draft。"""
    _assert_remote_route(res, "consult", label=label)


def _assert_clarification(res: dict, *, label: str) -> None:
    """Ambiguous：input_required + missing_information + data.route_target=local；无 draft；answer 含可接受澄清词。"""
    bs._check(res.get("status") == "input_required", f"{label}未转为澄清 input_required")
    bs._check(
        res.get("result_type") == "missing_information",
        f"{label}result_type非 missing_information",
    )
    _assert_route_target(res, "local", label=label)
    _assert_no_draft(res, label=label)
    answer = res.get("answer")
    _assert_truthy(answer, label=label)
    bs._check(
        any(token in answer for token in _CLARIFY_TOKENS),
        f"{label}澄清answer缺少可接受澄清词",
    )
    _assert_no_sensitive(res, label=label)


# --------------------------------------------------------------------------
# 测试矩阵：五类各 20 条（case_id, 自然表达）。
# 期望 target 由下表本身决定；不转成本地分类器 oracle。
# --------------------------------------------------------------------------

# 1) leave_transaction：明确新建/补登请假，故意缺字段以停在 Draft input_required。
_LEAVE_CASES: list[tuple[str, str]] = [
    ("colloquial_year", "我想请年假"),
    ("colloquial_days", "我想请几天年假"),
    ("invert_leave", "年假我想休一天"),
    ("backfill_friday", "帮我补登上周五的调休"),
    ("next_wednesday", "下周三想请一天假"),
    ("paternity_2d", "请两天陪产假"),
    ("marriage", "我要请婚假"),
    ("sick_from_monday", "我申请从下周一开始请病假"),
    ("tomorrow_annual", "明天想休年假"),
    ("personal_affair", "下周一我想请事假"),
    ("compassion", "我要请一天探亲假"),
    ("day_after_comp", "后天请一天调休"),
    ("friday_pm", "这周五下午我想请一天假"),
    ("next_month_3d", "我下个月要休三天年假"),
    ("backfill_15", "补登一下上个月15号的病假"),
    ("full_pay_sick", "我要请全薪病假"),
    ("one_day_le", "麻烦帮我请一天假期"),
    ("mar8", "3月8号我想要休假一天"),
    ("annual_from_56", "我请两天年假从5月6号开始"),
    ("half_day_sick", "明天上午请半天病假"),
    ("half_day_annual_dated", "2026年10月21日上午半天年休假"),
]

# 2) employee_self_data：明确「我/本人」的余额、指定假种、医疗期、工龄、参工、年假折算。
_EMPLOYEE_CASES: list[tuple[str, str]] = [
    ("my_all_balance", "我的假期余额"),
    ("my_medical", "我的医疗期余额"),
    ("my_tenure", "我的工龄"),
    ("annual_calc", "我的年假怎么折算"),
    ("childcare_days", "我还有几天育儿假"),
    ("comp_rest", "我的调休还有多少"),
    ("sick_balance", "我的病假余额"),
    ("full_pay_sick", "我的全薪病假还剩多少"),
    ("annual_2026", "我2026年的年休假余额"),
    ("annual_days", "我还有几天年假"),
    ("annual_balance", "我的年假余额还有多少"),
    ("comp_rest_year", "我今年的调休剩多少"),
    ("marriage_notfound", "我的婚假余额"),
    ("service_years", "我的参工年限"),
    ("join_time", "我的参工时间"),
    ("paternity_notfound", "我的陪产假余额"),
    ("maternity_notfound", "我的产假余额"),
    ("compassion_notfound", "我的探亲假余额"),
    ("balance_remain", "我的假期还剩多少天"),
    ("annual_remain", "我的年假还剩多少天"),
]

# 3) hr_consultation：制度/政策/系统操作/薪酬福利/地区育儿假/材料要求等，
#    必含击穿旧 `_is_leave_intent` 的「我想...假」问法。
_CONSULT_CASES: list[tuple[str, str]] = [
    ("annual_rule_want", "我想了解年假制度"),
    ("annual_policy_ask", "我想问问年假政策"),
    ("annual_consult", "关于年假制度我想咨询"),
    ("annual_rule", "公司年假的休假规定是什么"),
    ("annual_process", "年假的申请流程是怎样的"),
    ("sick_policy_want", "我想了解公司的病假政策"),
    ("compensation", "公司的薪酬福利制度有哪些"),
    ("childcare_region", "地区育儿假怎么申请"),
    ("childcare_material", "育儿假需要什么材料"),
    ("system_submit", "怎么在系统里提交请假申请"),
    ("attendance_makeup", "HR系统怎么补卡"),
    ("leave_types", "公司都有哪些假期种类"),
    ("annual_days", "年假可以休几天"),
    ("overtime_comp", "我想了解加班调休政策"),
    ("attendance_rule", "公司的考勤规定是什么"),
    ("onboard_material", "怎么补办入职材料"),
    ("social_insurance", "社保公积金怎么缴纳"),
    ("sick_salary", "我想了解病假工资怎么算"),
    ("long_sick", "公司对超长病假怎么处理"),
    ("resign_cert", "离职证明需要什么"),
]

# 4) attendance_calculation：明确迟到/早退分钟数与量化请求；时长明确以避开月度免扣追问。
_ATTENDANCE_CASES: list[tuple[str, str]] = [
    ("late_11", "本月此前迟到免扣2次、早退免扣2次，今天迟到11分钟扣多少？"),
    ("late_17", "本月此前迟到免扣2次、早退免扣2次，今天迟到17分钟扣多少？"),
    ("early_30", "本月此前迟到免扣2次、早退免扣2次，今天早退30分钟扣多少？"),
    ("late_59", "本月此前迟到免扣2次、早退免扣2次，今天迟到59分钟扣多少？"),
    ("late_60", "今天迟到60分钟怎么算？"),
    ("late_65", "今天迟到65分钟怎么算？"),
    ("early_90", "今天早退90分钟怎么算？"),
    ("late_239_abs", "今天迟到239分钟算旷工几天？"),
    ("late_240_abs", "今天迟到240分钟算旷工几天？"),
    ("late_250_abs", "今天迟到250分钟算旷工几天？"),
    ("late_11_money", "本月此前迟到免扣2次、早退免扣2次，今天迟到11分钟要扣多少钱？"),
    ("late_17_money", "本月此前迟到免扣2次、早退免扣2次，今天迟到17分钟要扣多少？"),
    ("early_30_how", "本月此前迟到免扣2次、早退免扣2次，今天早退30分钟怎么算？"),
    ("late_59_money", "本月此前迟到免扣2次、早退免扣2次，今天迟到59分钟扣多少钱？"),
    ("late_60_money", "今天迟到60分钟扣多少？"),
    ("early_90_money", "今天早退90分钟扣多少？"),
    ("late_65_how", "今天迟到65分钟怎么扣？"),
    ("late_239_how", "今天迟到239分钟怎么算旷工几天？"),
    ("late_240_how", "今天迟到240分钟算旷工多久？"),
    ("late_250_how", "今天迟到250分钟扣多少？"),
]

# 5) needs_clarification：无法分辨办理/余额/制度的短语，必须由 local Root 结构化追问。
_CLARIFY_CASES: list[tuple[str, str]] = [
    ("annual", "年假"),
    ("childcare", "育儿假"),
    ("comp_rest", "调休"),
    ("late", "迟到"),
    ("early", "早退"),
    ("sick", "病假"),
    ("attendance", "考勤"),
    ("balance", "余额"),
    ("annual_standard", "年休假"),
    ("vacation", "休假"),
    ("holiday", "假期"),
    ("marriage", "婚假"),
    ("personal", "事假"),
    ("compassion", "探亲假"),
    ("paternity", "陪产假"),
    ("shift_swap", "调班"),
    ("late_arr", "晚到"),
    ("absent", "缺勤"),
    ("maternity", "产假"),
    ("comp_alt", "倒休"),
]


# --------------------------------------------------------------------------
# 参数化验收：各类独立命名，可逐条独立报告。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,phrase", _LEAVE_CASES)
async def test_leave_transaction_routes_to_local_draft(probes, subject_a, case_id, phrase) -> None:
    """Leave 意图必须落到 local Leave 草稿（route_target=local + input_required + data.draft）。"""
    data = await _route(probes, subject_a, phrase)
    _assert_leave_route(data, label=f"leave:{case_id}")


@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,phrase", _EMPLOYEE_CASES)
async def test_employee_self_data_routes_to_employee_data(probes, subject_a, case_id, phrase) -> None:
    """员工本人数据意图必须落到 Employee Data A2A（route_target=employee_data）。"""
    data = await _route(probes, subject_a, phrase)
    _assert_employee_route(data, label=f"employee:{case_id}")


@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,phrase", _CONSULT_CASES)
async def test_hr_consultation_routes_to_consult(probes, subject_a, case_id, phrase) -> None:
    """HR 制度/政策咨询意图必须落到 Consult A2A（route_target=consult）。"""
    data = await _route(probes, subject_a, phrase)
    _assert_consult_route(data, label=f"consult:{case_id}")


@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,phrase", _ATTENDANCE_CASES)
async def test_attendance_calculation_routes_to_consult(probes, subject_a, case_id, phrase) -> None:
    """考勤量化计算意图必须落到 Consult A2A（route_target=consult，无草稿）。"""
    data = await _route(probes, subject_a, phrase)
    _assert_consult_route(data, label=f"attendance:{case_id}")


@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,phrase", _CLARIFY_CASES)
async def test_needs_clarification_routes_to_local_root(probes, subject_a, case_id, phrase) -> None:
    """歧义短语必须由 local Root 结构化追问（route_target=local + input_required + 无 draft + 澄清词）。"""
    data = await _route(probes, subject_a, phrase)
    _assert_clarification(data, label=f"clarify:{case_id}")
