"""对话评测跑批脚本：`uv run pytest -m eval -v`。

需要真实方舟模型 Key（.env 配置 MODEL_AGENT_API_KEY）。无 Key 时整体 skip，
标注"待 Key 试跑"——不伪造评测通过。

挂桩策略：monkeypatch hr_agent.tools.gaia.client.GaiaClient.request，
按 path 分派固定响应（员工 sex=F、排班 7-27 OFF、年假余额 remain=4 等）。
"""
import os
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml
from google.genai import types

from hr_agent.agents.main_agent import root_agent
from hr_agent.tools.gaia import client as gaia_client_module

DUMMY_KEY = "dummy-for-struct-test-only"


def _has_real_key() -> bool:
    key = os.getenv("MODEL_AGENT_API_KEY")
    return bool(key) and key != DUMMY_KEY


EVAL_SKIP_REASON = (
    "待 Key 试跑：评测需要真实方舟模型 Key（.env 配置 MODEL_AGENT_API_KEY），"
    "当前为占位值或未配置。"
)

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not _has_real_key(), reason=EVAL_SKIP_REASON),
]

CASES_PATH = Path(__file__).parent / "cases.yaml"


def _load_cases():
    with open(CASES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


CASES = _load_cases()

# ---------- 盖亚接口挂桩数据（与 tests/ 下单测同构，但整合为一份）----------
STUB_OAUTH = {"result": True, "code": 200, "data": "fake.jwt"}

STUB_BALANCE = {
    "code": 200,
    "details": {"employeeData": [{"employeeDetailData": [
        {"effectiveYear": "2026", "leaveCode": "A31", "leaveName": "年休假",
         "leaveUsed": 1, "leaveTotal": 5, "leaveRemain": 4},
        {"effectiveYear": "2026", "leaveCode": "A08", "leaveName": "陪产假",
         "leaveUsed": 0, "leaveTotal": 15, "leaveRemain": 15},
    ]}]},
}

STUB_PERMISSIONS = {"result": True, "data": [
    {"LeaveCode": "A31", "LeaveType": "年休假"},
    {"LeaveCode": "A08", "LeaveType": "陪产假"},
    {"LeaveCode": "C01", "LeaveType": "事假"},
    {"LeaveCode": "B01", "LeaveType": "病假"},
    {"LeaveCode": "A02", "LeaveType": "调休假"},
]}

STUB_MEDICAL = {"details": [{"quota": 24, "used": 3, "balance": 21}]}

STUB_EMPLOYEE = {"details": [{"sex": "F", "socialService": "6 年 4 月 0 天",
                              "socialServiceDate": "2019-11-03"}]}

# 排班日期相对今天生成，不写死具体日期：写死会随时间推移失效——case 里的
# "明天"某天就会落到 stub 范围外，模型查不到排班便反复重试直至陷入循环
# （gender_mismatch 曾因此卡死）。窗口取 today-7..today+14，覆盖补登与提前请假。
_TODAY = date.today()
REST_DAY_OFFSET = -2      # 前天为休息日，供 rest_day case 命中


def _day(offset: int) -> str:
    return (_TODAY + timedelta(days=offset)).isoformat()


STUB_SCHEDULE_ROWS = [
    {"shiftDate": _day(o), "shiftCode": "OFF01", "shiftName": "休息",
     "startTime": "00:00", "endTime": "00:00"}
    if o == REST_DAY_OFFSET else
    {"shiftDate": _day(o), "shiftCode": "SCQY01", "shiftName": "白班",
     "startTime": "08:00", "endTime": "17:00"}
    for o in range(-7, 15)
]

# case 文本里的日期占位符（用尖括号而非大括号，避免与 _transparent_data_ 的 JSON 冲突）
_DATE_TOKENS = {"<today>": 0, "<tomorrow>": 1, "<yesterday>": -1,
                "<rest_day>": REST_DAY_OFFSET}


def _resolve_dates(text: str) -> str:
    for token, offset in _DATE_TOKENS.items():
        if token in text:
            text = text.replace(token, _day(offset))
    return text


def _stub_request(self, env, method, path, *, json_body=None, params=None,
                  extra_headers=None, tenant=None):
    """按 path 分派固定响应。签名与 GaiaClient.request 一致。"""
    if "/oauth" in path:
        return STUB_OAUTH
    if "getemployeeleaveremaindata" in path:
        return STUB_BALANCE
    if "getEmployeeCanApplyLeaveType" in path:
        return STUB_PERMISSIONS
    if "medical/period/info/get" in path:
        return STUB_MEDICAL
    if "person/search-effective" in path:
        return STUB_EMPLOYEE
    if "getScheduleData" in path:
        # 按请求的日期范围过滤，模拟真实盖亚 API 行为（真实 API 只返回区间内排班）。
        # 不过滤会导致 get_schedule(D,D) 拿回整个窗口，submit_leave 取首条
        # （可能是休息日）误判。
        sd = (json_body or {}).get("startDate", "")
        ed = (json_body or {}).get("endDate", sd)
        rows = [r for r in STUB_SCHEDULE_ROWS if sd <= r["shiftDate"] <= ed]
        return {"details": {"employeeData": [{"employeeDetailData": rows}]}}
    return {"result": True, "data": []}


@pytest.fixture
def stub_gaia(monkeypatch):
    """挂桩盖亚接口，让评测聚焦于模型行为而非外部服务。"""
    monkeypatch.setattr(gaia_client_module.GaiaClient, "request", _stub_request)


class _FakeResp:
    status_code = 200
    headers = {"Content-Length": "100"}

    def iter_content(self, chunk_size=8192):
        yield b"# test\nhello world"

    def raise_for_status(self):
        pass


@pytest.fixture
def stub_requests(monkeypatch):
    """挂桩文档下载，避免评测时真实请求外部 URL。"""
    import hr_agent.tools.rules.parse_document as pd_mod

    monkeypatch.setattr(pd_mod.requests, "get", lambda *args, **kwargs: _FakeResp())


BIZ_STATE = {
    "employeeId": "E001",
    "corp_id": "corp1",
    "client_secret": "sec",
    "grant_type": "client_credentials",
}


def _user_content(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def _collect_event_data(events):
    """从事件流收集工具调用名与最终文本。

    doubao-seed-1.6 是推理模型，会输出大量 thinking part（part.thought=True）。
    若不过滤，最终文本会混入完整推理链（"让我想想...首先..."），污染关键词断言。
    对齐 veADK Runner.run() 的处理：跳过 thought part，只收真实输出。
    """
    tool_calls = []
    final_texts = []
    for ev in events:
        if not ev.content or not ev.content.parts:
            continue
        for p in ev.content.parts:
            fc = getattr(p, "function_call", None)
            if fc is not None and getattr(fc, "name", None):
                tool_calls.append(fc.name)
            txt = getattr(p, "text", None)
            if txt is not None and txt.strip() and not getattr(p, "thought", False):
                final_texts.append(txt)
    return tool_calls, "\n".join(final_texts)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_eval_case(case, stub_gaia, stub_requests):
    """逐 case 跑多轮对话，断言 expect_tool / expect_no_tool / expect_keywords / expect_not_keywords / expect_marker。"""
    # 延迟 import Runner：避免无 Key 时模块加载就触发 root_agent 实例化失败
    from veadk import Runner

    runner = Runner(agent=root_agent, app_name="hr-agent-eval",
                    user_id="eval-user")
    session_id = f"eval-{case['id']}"

    # run_async 是 ADK 原生方法，不自动建 session（自动建 session 的逻辑只在
    # veADK 包装的 run() 里）。须先显式创建 session，否则抛 SessionNotFoundError。
    # 写法对齐 veadk Runner.run() 内部的 create_session 调用。
    await runner.short_term_memory.create_session(
        app_name="hr-agent-eval", user_id="eval-user", session_id=session_id
    )

    tool_calls: list[str] = []
    final_text = ""
    for i, turn in enumerate(case["turns"]):
        events = []
        async for ev in runner.run_async(
            user_id="eval-user",
            session_id=session_id,
            new_message=_user_content(_resolve_dates(turn)),
            state_delta=BIZ_STATE if i == 0 else None,
        ):
            events.append(ev)
        tc, ft = _collect_event_data(events)
        tool_calls.extend(tc)
        if ft:
            final_text = ft

    # ---------- 断言期望 ----------
    if "expect_tool" in case:
        for t in case["expect_tool"]:
            assert t in tool_calls, (
                f"{case['id']}: 期望调用工具 {t}，实际调用 {tool_calls}"
            )
    if "expect_any_tool" in case:
        # 命中其一即可（如"还有几天年假"可走 get_leave_balance 或更完整的组合工具 calc_annual_leave）
        assert any(t in tool_calls for t in case["expect_any_tool"]), (
            f"{case['id']}: 期望调用工具之一 {case['expect_any_tool']}，实际调用 {tool_calls}"
        )
    if "expect_no_tool" in case:
        for t in case["expect_no_tool"]:
            assert t not in tool_calls, (
                f"{case['id']}: 期望不调用工具 {t}，实际调用 {tool_calls}"
            )
    if "expect_keywords" in case:
        for kw in case["expect_keywords"]:
            assert kw in final_text, (
                f"{case['id']}: 期望回复含 '{kw}'，实际回复 {final_text!r}"
            )
    if "expect_any_keyword" in case:
        # 命中其一即可，容纳模型同义表达波动（如"分开提交"≈"先选其中一种"）
        assert any(kw in final_text for kw in case["expect_any_keyword"]), (
            f"{case['id']}: 期望回复含其一 {case['expect_any_keyword']}，实际回复 {final_text!r}"
        )
    if "expect_not_keywords" in case:
        for kw in case["expect_not_keywords"]:
            assert kw not in final_text, (
                f"{case['id']}: 期望回复不含 '{kw}'，实际回复 {final_text!r}"
            )
    if "expect_marker" in case:
        assert case["expect_marker"] in final_text, (
            f"{case['id']}: 期望标记 {case['expect_marker']}，实际 {final_text!r}"
        )
