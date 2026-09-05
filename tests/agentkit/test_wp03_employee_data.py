"""WP-03 员工本人假期余额远端验收：一个不变量。

已部署 Employee Data Runtime 是当前员工本人数据的唯一只读 Authority，必须通过真实
HTTPS A2A 返回各种假期余额；指定假种不能拿第一行冒充；day/hour、effective_year、
approving/freeze 必须从结构化 data 到确定性 answer 一致；不能泄露 employee_id；
政策、办理请假、跨员工查询必须在 Employee Data 自身拒绝。保留医疗期、工龄、年假折算。

范围：真实 HTTPS A2A 调用（AgentKit 开发 Runtime 的 employee_data）。无本地应用/模型/
服务、无 fake-model、无 ASGI。全部通过 business_support.request_task 直连 employee_data。

安全：本文件不改任何生产代码；敏感断言全部走 business_support._check()，避免 pytest
断言内省打印主体/oracle/ref/原始响应；不打印凭据/env/oracle，不 import apps/packages/
veadk，不 mock/ASGI/localhost/skip/xfail。期望数据来自冻结的发布 fixture，不读取运行时
环境推断。

注：当前云端 stub 的 leave_balances 为空，故余额成功场景（用例1~3）应真实 RED；
空列表 not_found（用例4/5）与安全拒绝（用例6）及既有能力（用例7）可能绿。
"""

from __future__ import annotations

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# --------------------------------------------------------------------------
# 冻结的发布 fixture：subject A 对应记录的 leave_balances（顺序稳定）。
# 仅记录发布值；不读取运行时环境构造期望。
# --------------------------------------------------------------------------
SUBJECT_A_BALANCES: list[dict] = [
    {"leave_code": "A31", "leave_name": "年休假", "effective_year": "2025",
     "unit": "day", "total": 5, "used": 4, "remain": 1, "approving": 0, "freeze": 0},
    {"leave_code": "A31", "leave_name": "年休假", "effective_year": "2026",
     "unit": "day", "total": 6, "used": 2, "remain": 4, "approving": 1, "freeze": 1},
    {"leave_code": "A47", "leave_name": "育儿假", "effective_year": "2026",
     "unit": "day", "total": 10, "used": 3, "remain": 7, "approving": 1, "freeze": 2},
    {"leave_code": "A02", "leave_name": "调休假", "effective_year": "2026",
     "unit": "hour", "total": 12, "used": 4, "remain": 8, "approving": 2, "freeze": 2},
    {"leave_code": "B01", "leave_name": "病假", "effective_year": "2026",
     "unit": "day", "total": 10, "used": 2, "remain": 8, "approving": 0, "freeze": 0},
    {"leave_code": "A49", "leave_name": "全薪病假", "effective_year": "2026",
     "unit": "day", "total": 5, "used": 1, "remain": 4, "approving": 0, "freeze": 0},
]

# 指定假种：message → 期望（leave_name, leave_code, year, unit, remain）。
_TYPE_CASES: list[tuple[str, str, str, str, str, int]] = [
    ("我还有几天育儿假", "育儿假", "A47", "2026", "day", 7),
    ("我的调休还有多少", "调休假", "A02", "2026", "hour", 8),
    ("我的病假余额", "病假", "B01", "2026", "day", 8),
    ("我的全薪病假还剩多少", "全薪病假", "A49", "2026", "day", 4),
]

# Employee Data 自身拒绝：message → 精确 error_code。
_REJECT_CASES: list[tuple[str, str]] = [
    ("四川育儿假有几天", "policy_query_not_allowed"),
    ("育儿假怎么申请", "policy_query_not_allowed"),
    ("我想请一天年假", "leave_request_not_allowed"),
    ("查询同事工号EMP-0002的年假余额", "cross_employee_query_not_allowed"),
]


# --------------------------------------------------------------------------
# fixtures（与 WP-01 一致：subject A 为 oracle 第一条，subject B 为第二条）
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def identity_oracle() -> dict[str, OracleSubject]:
    return bs.load_identity_oracle()


@pytest.fixture(scope="session")
def subject_a(identity_oracle) -> OracleSubject:
    return list(identity_oracle.values())[0]


@pytest.fixture(scope="session")
def subject_b(identity_oracle) -> OracleSubject:
    return list(identity_oracle.values())[1]


def _direct(subject: OracleSubject, text: str):
    """构造 Employee Data 结构化查询消息（内部可信 A2A 契约，非匿名）。"""
    internal = bs.derive_internal_user_id(subject.subject_kind, subject.subject_id)
    return bs.employee_message(text, internal_user_id=internal)


# --------------------------------------------------------------------------
# 复用断言（均不打印主体/ref/原始响应/oracle）
# --------------------------------------------------------------------------
def _unit_label(unit: str | None) -> str:
    return "小时" if (unit or "day") == "hour" else "天"


def _assert_no_employee_id(obj, *, label: str) -> None:
    """递归断言响应不含 employee_id 键或子串，杜绝泄露本人 id。"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            bs._check(key != "employee_id", f"{label}泄露了employee_id键")
            _assert_no_employee_id(value, label=label)
    elif isinstance(obj, list):
        for value in obj:
            _assert_no_employee_id(value, label=label)
    elif isinstance(obj, str):
        bs._check("employee_id" not in obj, f"{label}响应文本包含employee_id")


def _assert_row_matches(row, expected: dict, *, label: str) -> None:
    """逐字段校验余额行；年份做 str 归一，数值用 Python ==（int/float 均可）。"""
    bs._check(row.get("leave_name") == expected["leave_name"], f"{label}假种名不一致")
    bs._check(row.get("leave_code") == expected["leave_code"], f"{label}假种编码不一致")
    bs._check(row.get("unit") == expected["unit"], f"{label}单位不一致")
    bs._check(
        str(row.get("effective_year")) == str(expected["effective_year"]),
        f"{label}年份不一致",
    )
    for key in ("total", "used", "remain", "approving", "freeze"):
        bs._check(row.get(key) == expected[key], f"{label}字段{key}不一致")


def _frozen_full_spec(leave_code: str, year: str) -> dict:
    for row in SUBJECT_A_BALANCES:
        if row["leave_code"] == leave_code and str(row["effective_year"]) == str(year):
            return row
    raise AssertionError("冻结的余额行缺失")


def _extract_balance_rows(data: dict) -> list[dict]:
    """兼容 data 返回单行 leave_balance 或多行 leave_balances；否则空。"""
    payload = data.get("data")
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("leave_balances"), list):
        return payload["leave_balances"]
    if isinstance(payload.get("leave_balance"), dict):
        return [payload["leave_balance"]]
    return []


def _render_all_balances_answer(rows: list[dict]) -> str:
    """按通用确定格式重排全部余额 answer；数字/年份取自返回行，保持 int/float 一致。"""
    lines = []
    for row in rows:
        year = row.get("effective_year")
        suffix = f"（{year}年）" if year else ""
        lines.append(
            f"{row.get('leave_name')}：{row.get('remain')} "
            f"{_unit_label(row.get('unit'))}{suffix}"
        )
    return "您的假期余额：" + "；".join(lines) + "。"


# --------------------------------------------------------------------------
# 用例1：subject A 我的假期余额 → 全部余额
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_subject_a_full_balances_exact(probes, subject_a) -> None:
    data = await bs.request_task(
        probes, "employee_data", _direct(subject_a, "我的假期余额")
    )
    bs._check(data.get("status") == "succeeded", "主体A全量假期余额未成功")
    bs._check(data.get("query_type") == "leave_balance_all", "主体A未返回leave_balance_all")
    bs._check(data.get("source") == "stub", "主体A全量余额source非stub")
    bs._check(data.get("employee_ref") == subject_a.employee_ref, "主体A全量余额employee_ref不一致")
    bs._check(data.get("error_code") is None, "主体A全量余额出现非预期错误码")
    payload = data.get("data")
    bs._check(
        isinstance(payload, dict) and isinstance(payload.get("leave_balances"), list),
        "主体A全量余额未返回行列表",
    )
    rows = payload["leave_balances"]
    bs._check(len(rows) == len(SUBJECT_A_BALANCES), "主体A全量余额行数不一致")
    for i, (row, expected) in enumerate(zip(rows, SUBJECT_A_BALANCES)):
        _assert_row_matches(row, expected, label=f"主体A余额行{i}")
    bs._check(
        data.get("answer") == _render_all_balances_answer(rows),
        "主体A全量余额answer与data不一致",
    )
    _assert_no_employee_id(data, label="主体A全量余额")


# --------------------------------------------------------------------------
# 用例2：指定假种参数化 → 精确的 data.leave_balance / answer / unit
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message,leave_name,leave_code,year,unit,remain", _TYPE_CASES
)
async def test_subject_a_by_type_exact(
    probes, subject_a, message, leave_name, leave_code, year, unit, remain
) -> None:
    data = await bs.request_task(probes, "employee_data", _direct(subject_a, message))
    tag = leave_name
    bs._check(data.get("status") == "succeeded", f"主体A{tag}余额未成功")
    bs._check(data.get("query_type") == "leave_balance_by_type", f"主体A{tag}未按假种查询")
    bs._check(data.get("source") == "stub", f"主体A{tag}source非stub")
    bs._check(data.get("employee_ref") == subject_a.employee_ref, f"主体A{tag}employee_ref不一致")
    bs._check(data.get("error_code") is None, f"主体A{tag}出现非预期错误码")
    payload = data.get("data")
    bs._check(
        isinstance(payload, dict) and isinstance(payload.get("leave_balance"), dict),
        f"主体A{tag}未返回单行leave_balance",
    )
    row = payload["leave_balance"]
    expected = _frozen_full_spec(leave_code, year)
    _assert_row_matches(row, expected, label=f"主体A{tag}")
    bs._check(
        data.get("answer")
        == f"您的{row.get('leave_name')}余额为{row.get('remain')} "
        f"{_unit_label(row.get('unit'))}。",
        f"主体A{tag}answer与余额不一致",
    )
    _assert_no_employee_id(data, label=f"主体A{tag}")


# --------------------------------------------------------------------------
# 用例3：指定 2026 年休假 → 选 2026 行，不得用 2025 年第一条
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_subject_a_annual_leave_2026_selects_2026_row(probes, subject_a) -> None:
    data = await bs.request_task(
        probes, "employee_data", _direct(subject_a, "我2026年的年休假余额")
    )
    bs._check(data.get("status") == "succeeded", "主体A2026年假未成功")
    bs._check(data.get("source") == "stub", "主体A2026年假source非stub")
    bs._check(data.get("employee_ref") == subject_a.employee_ref, "主体A2026年假employee_ref不一致")
    rows = _extract_balance_rows(data)
    bs._check(bool(rows), "主体A2026年假未返回余额行")
    selected = next(
        (r for r in rows if r.get("leave_name") == "年休假"
         and str(r.get("effective_year")) == "2026"),
        None,
    )
    bs._check(selected is not None, "主体A2026年假未选择2026年行")
    expected = _frozen_full_spec("A31", "2026")
    _assert_row_matches(selected, expected, label="主体A2026年假")
    answer = str(data.get("answer") or "")
    bs._check("4" in answer and "天" in answer, "主体A2026年假answer未用4天")
    bs._check("2025" not in answer, "主体A2026年假answer误用2025年")
    bs._check("余额为1 天" not in answer, "主体A2026年假answer误用第一条1天")
    _assert_no_employee_id(data, label="主体A2026年假")


# --------------------------------------------------------------------------
# 用例4：无婚假 → not_found，不得返回年休假/第一行/0
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_subject_a_marriage_leave_not_found(probes, subject_a) -> None:
    data = await bs.request_task(
        probes, "employee_data", _direct(subject_a, "我的婚假余额")
    )
    bs._check(data.get("status") == "not_found", "无婚假未被判为not_found")
    bs._check(data.get("error_code") == "leave_balance_not_found", "无婚假未返回leave_balance_not_found")
    bs._check(data.get("query_type") == "leave_balance_by_type", "无婚假未按假种查询")
    bs._check(data.get("data") is None, "无婚假不应返回余额数据")
    _assert_no_employee_id(data, label="无婚假")


# --------------------------------------------------------------------------
# 用例5：subject B 空余额 → 同样 not_found，不得伪造空余额成功
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_subject_b_empty_balances_not_found(probes, subject_b) -> None:
    data = await bs.request_task(
        probes, "employee_data", _direct(subject_b, "我的假期余额")
    )
    bs._check(data.get("status") == "not_found", "主体B空余额未被判为not_found")
    bs._check(data.get("error_code") == "leave_balance_not_found", "主体B空余额未返回leave_balance_not_found")
    bs._check(data.get("query_type") == "leave_balance_all", "主体B空余额未按全部查询")
    bs._check(data.get("data") is None, "主体B空余额不应伪造空余额成功")
    _assert_no_employee_id(data, label="主体B空余额")


# --------------------------------------------------------------------------
# 用例6：Employee Data 自身拒绝参数化
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize("message,error_code", _REJECT_CASES)
async def test_employee_data_rejects_scope(probes, subject_a, message, error_code) -> None:
    data = await bs.request_task(probes, "employee_data", _direct(subject_a, message))
    bs._check(data.get("status") == "rejected", "出界查询未被Employee Data拒绝")
    bs._check(data.get("error_code") == error_code, "出界查询error_code不精确")
    bs._check(data.get("data") is None, "出界查询不应返回数据")
    _assert_no_employee_id(data, label="出界查询")


# --------------------------------------------------------------------------
# 用例7：既有能力（不硬编码非余额 oracle 数字；数字来自 data）
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message,query_type",
    [
        ("我的医疗期余额", "medical_period"),
        ("我的工龄", "employment_info"),
        ("我的年假怎么折算", "annual_leave_calculation"),
    ],
)
async def test_subject_a_existing_capabilities(
    probes, subject_a, message, query_type
) -> None:
    data = await bs.request_task(probes, "employee_data", _direct(subject_a, message))
    bs._check(data.get("status") == "succeeded", f"{query_type}未成功")
    bs._check(data.get("query_type") == query_type, f"未返回{query_type}")
    bs._check(data.get("source") == "stub", f"{query_type}source非stub")
    bs._check(data.get("employee_ref") == subject_a.employee_ref, f"{query_type}employee_ref不一致")
    bs._check(data.get("error_code") is None, f"{query_type}出现非预期错误码")
    payload = data.get("data")
    bs._check(isinstance(payload, dict) and payload, f"{query_type}结构化data缺失")
    answer = str(data.get("answer") or "")
    if query_type == "medical_period":
        bs._check("balance" in payload, "医疗期结果缺少balance")
        bs._check(str(payload["balance"]) in answer, "医疗期answer数字与data不一致")
    elif query_type == "employment_info":
        bs._check("social_service_year" in payload, "工龄结果缺少social_service_year")
        for key in ("social_service_year", "social_service_month", "social_service_day"):
            bs._check(str(payload[key]) in answer, f"工龄answer缺少{key}数字")
    else:
        annual = payload.get("annual_leave")
        bs._check(isinstance(annual, dict) and "mode" in annual, "年假折算缺少mode")
        mode = annual["mode"]
        bs._check(mode in ("flat", "split"), "年假折算mode非预期")
        if mode == "flat":
            bs._check("quota" in annual, "年假折算flat缺少quota")
            bs._check(str(annual["quota"]) in answer, "年假折算answer缺少quota")
        else:
            bs._check("before" in annual and "after" in annual, "年假折算split缺少before/after")
            bs._check(
                str(annual["before"]) in answer and str(annual["after"]) in answer,
                "年假折算answer缺少before/after",
            )
    _assert_no_employee_id(data, label=query_type)
