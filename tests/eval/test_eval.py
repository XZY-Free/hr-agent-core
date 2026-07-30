"""对话评测跑批脚本：`uv run pytest -m eval -v`。

需要真实方舟模型 Key（.env 配置 MODEL_AGENT_API_KEY）。无 Key 时整体 skip，
标注"待 Key 试跑"——不伪造评测通过。

挂桩策略：monkeypatch hr_agent.tools.gaia.client.GaiaClient.request，
按 path 分派固定响应（员工 sex=F、排班 7-27 OFF、年假余额 remain=4 等）。
"""
import json
import os
import time
from datetime import date, datetime, timedelta
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

# case 文本里的日期占位符。用尖括号而非大括号，避免与 case 里可能出现的 JSON 冲突。
# 当前无 case 使用——口语日期交给模型换算本身就是被测能力；保留是因为日期是本项目
# 的核心维度，将来若要验跨月/跨年场景需要写死真实日期。
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
    """挂桩文档下载。内容取多段落的真实通知形态——早先用的是单行
    "# test\\nhello world"，内容太短会诱导模型照抄原文（连转义符一起抄），
    验不到"读懂文档并转述关键信息"这个真正要测的能力。"""

    status_code = 200
    headers = {"Content-Length": "400"}

    def iter_content(self, chunk_size=8192):
        yield (
            "# 2026 年春节假期安排通知\n\n"
            "一、放假时间：2 月 16 日至 2 月 22 日，共 7 天，2 月 23 日（周一）正常上班。\n"
            "二、值班安排：假期值班人员由各部门自行排定，值班表请于 2 月 10 日前\n"
            "报人力资源部备案，值班当日按加班处理。\n"
            "三、考勤要求：节前最后一个工作日与节后首个工作日均需正常打卡，\n"
            "因故不能到岗的请提前提交请假申请。\n"
        ).encode("utf-8")

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
    trace = _collect_turn(events)
    return trace["tool_calls"], trace["text"]


def _collect_turn(events) -> dict:
    """把一轮事件流拆成可读轨迹：工具调用（名/参数/返回）、思考量、输出文本。

    thought part 只统计字数不进 text——doubao-seed-1.6 是推理模型，推理链混进
    最终文本会污染关键词断言（对齐 veADK Runner.run() 的处理）。
    """
    steps, tool_calls, texts = [], [], []
    thought_chars = 0
    for ev in events:
        if not ev.content or not ev.content.parts:
            continue
        author = getattr(ev, "author", None)
        for p in ev.content.parts:
            fc = getattr(p, "function_call", None)
            if fc is not None and getattr(fc, "name", None):
                tool_calls.append(fc.name)
                steps.append({"kind": "call", "author": author, "name": fc.name,
                              "args": dict(fc.args or {})})
                continue
            fr = getattr(p, "function_response", None)
            if fr is not None and getattr(fr, "name", None):
                steps.append({"kind": "result", "author": author, "name": fr.name,
                              "response": fr.response})
                continue
            txt = getattr(p, "text", None)
            if txt is None or not txt.strip():
                continue
            if getattr(p, "thought", False):
                thought_chars += len(txt)
                steps.append({"kind": "thought", "author": author, "chars": len(txt)})
            else:
                texts.append(txt)
                steps.append({"kind": "text", "author": author, "text": txt})
    return {"steps": steps, "tool_calls": tool_calls,
            "text": "\n".join(texts), "thought_chars": thought_chars}


# ---------- 执行轨迹日志 ----------
# 评测跑批的失败分两类：模型行为不符期望（断言失败）与基础设施故障（连接错误）。
# 两者在 pytest 输出里混在一起，且全量跑 22 条要 12 分钟、看不到中间过程，无法
# 判断"某条为何失败"。故逐 case 落盘完整轨迹：工具调用+参数+返回、思考量、
# 每轮耗时、相对跑批开始的时间偏移（用于判断故障是否与累积运行时长相关）。
EVAL_LOG_DIR = Path(__file__).parent / "logs"
_RUN_START = time.monotonic()


def _fmt(value, limit: int = 400) -> str:
    """紧凑单行展示，超长截断——知识库检索返回可达数千字。"""
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[:limit]}…（共 {len(text)} 字）"


@pytest.fixture(scope="session")
def eval_log_path() -> Path:
    """整次跑批共用一个日志文件，逐 case 追加并即时 flush（中途崩溃也留证据）。"""
    EVAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = EVAL_LOG_DIR / f"eval-{datetime.now():%Y%m%d-%H%M%S}.log"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 评测执行轨迹 {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                f"# 今天={_TODAY.isoformat()} 休息日桩={_day(REST_DAY_OFFSET)} "
                f"排班窗口={_day(-7)}..{_day(14)}\n")
    print(f"\n[eval] 执行轨迹日志：{path}")
    return path


@pytest.fixture
def trace(request, eval_log_path):
    """收集单个 case 的执行轨迹。teardown 必定执行，故通过与失败都会落盘。"""
    rec = {"case": request.node.callspec.params["case"]["id"],
           "offset": time.monotonic() - _RUN_START, "turns": [], "error": None}
    yield rec
    _write_trace(eval_log_path, rec)


def _format_trace(rec: dict) -> str:
    """把一个 case 的执行轨迹渲染成可读文本（既写日志，也喂给评判模型）。"""
    lines = [f"[{rec['case']}] 开跑于跑批第 {rec['offset']:.0f}s"]
    for t in rec["turns"]:
        lines.append(f"\n  ── 第 {t['index'] + 1} 轮（{t['elapsed']:.1f}s）"
                     f" 用户：{_fmt(t['user'], 200)}")
        for s in t["trace"]["steps"]:
            who = s.get("author") or "?"
            if s["kind"] == "call":
                lines.append(f"     → [{who}] 调用 {s['name']}({_fmt(s['args'], 200)})")
            elif s["kind"] == "result":
                lines.append(f"     ← [{who}] {s['name']} 返回 {_fmt(s['response'])}")
            elif s["kind"] == "thought":
                lines.append(f"     · [{who}] 思考 {s['chars']} 字")
            else:
                lines.append(f"     ✎ [{who}] {_fmt(s['text'], 600)}")
    if rec["error"]:
        lines.append(f"\n  ✗ 异常：{rec['error']}")
    return "\n".join(lines)


def _write_trace(path: Path, rec: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 78}\n{_format_trace(rec)}\n"
                f"\n  结论：{rec.get('outcome', '未记录')}\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_eval_case(case, stub_gaia, stub_requests, trace):
    """逐 case 跑多轮对话，断言 expect_tool / expect_no_tool / expect_keywords / expect_not_keywords / expect_marker。

    执行轨迹落盘到 tests/eval/logs/，用于区分"模型行为不符期望"与"基础设施故障"。
    """
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
    all_texts: list[str] = []
    for i, turn in enumerate(case["turns"]):
        user_msg = _resolve_dates(turn)
        started = time.monotonic()
        events = []
        try:
            async for ev in runner.run_async(
                user_id="eval-user",
                session_id=session_id,
                new_message=_user_content(user_msg),
                state_delta=BIZ_STATE if i == 0 else None,
            ):
                events.append(ev)
        except Exception as e:
            # 连接类故障与模型行为问题要能分辨：记下发生在第几轮、已跑多久
            trace["error"] = f"{type(e).__name__}: {e}"
            trace["turns"].append({"index": i, "user": user_msg,
                                   "elapsed": time.monotonic() - started,
                                   "trace": _collect_turn(events)})
            trace["outcome"] = f"异常中断于第 {i + 1} 轮"
            raise
        turn_trace = _collect_turn(events)
        trace["turns"].append({"index": i, "user": user_msg,
                               "elapsed": time.monotonic() - started,
                               "trace": turn_trace})
        tool_calls.extend(turn_trace["tool_calls"])
        if turn_trace["text"]:
            final_text = turn_trace["text"]
            all_texts.append(turn_trace["text"])

    trace["outcome"] = f"跑完 {len(case['turns'])} 轮，工具={tool_calls}"

    # ---------- 断言期望 ----------
    # 包一层：断言失败的具体原因要写进轨迹日志，否则事后只能看到 pytest 的截断输出
    try:
        _assert_case(case, tool_calls, final_text, "\n".join(all_texts))
    except AssertionError as e:
        trace["outcome"] = f"断言失败 —— {e}"
        raise
    trace["outcome"] = f"通过（工具={tool_calls}）"


def _assert_case(case: dict, tool_calls: list[str], final_text: str,
                 dialog_text: str) -> None:
    """断言 case 期望。

    final_text 是最后一轮的回复，dialog_text 是各轮回复拼接。
    多轮 case 里"结论出现在哪一轮"取决于模型效率——如 rest_day，识别出休息日
    可能在第 1 轮（查排班后直接告知）也可能在第 2 轮（走 submit 被拒后转述），
    只看 final_text 会把"更早给出结论"误判为失败。故凡是验"说过某结论"的用
    expect_*_anywhere 在 dialog_text 上断言；验"最终回复必须是什么"的仍用
    final_text。
    """
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
    if "expect_keywords_anywhere" in case:
        for kw in case["expect_keywords_anywhere"]:
            assert kw in dialog_text, (
                f"{case['id']}: 期望对话中出现过 '{kw}'，各轮回复 {dialog_text!r}"
            )
    if "expect_any_keyword_anywhere" in case:
        assert any(kw in dialog_text for kw in case["expect_any_keyword_anywhere"]), (
            f"{case['id']}: 期望对话中出现过其一 {case['expect_any_keyword_anywhere']}，"
            f"各轮回复 {dialog_text!r}"
        )
