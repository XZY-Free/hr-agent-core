from types import SimpleNamespace

from apps.orchestrator.routing.page_jump import page_jump
from apps.orchestrator.callbacks.jump_marker import jump_marker_callback


def _ctx(state=None):
    return SimpleNamespace(state=state if state is not None else {})


def _text_response(text):
    return SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text=text)]))


def test_page_jump_sets_state():
    ctx = _ctx()
    r = page_jump("打卡明细", ctx)
    assert r["success"]
    assert ctx.state["pending_jump"] == "punch-details"
    assert r["data"]["code"] == "punch-details"


def test_page_jump_unknown_name():
    r = page_jump("不存在的页面", _ctx())
    assert not r["success"] and r["error_type"] == "unknown_page"
    # 错误消息要列出可选页面，模型才能换说法自我纠正
    assert "打卡明细" in r["message"] and "我的表单" in r["message"]


def test_callback_appends_marker_once():
    ctx = _ctx(state={"pending_jump": "punch-details"})
    out = jump_marker_callback(ctx, _text_response("已为您打开打卡明细。"))
    assert out is not None
    assert out.content.parts[0].text.endswith("[[JUMP:punch-details]]")
    assert "pending_jump" not in ctx.state   # 已清除


def test_callback_noop_without_pending():
    assert jump_marker_callback(_ctx({}), _text_response("你好")) is None


def test_callback_noop_when_pending_already_consumed():
    ctx = _ctx(state={"pending_jump": "punch-details"})
    jump_marker_callback(ctx, _text_response("打开"))
    # 第二次 state 已清，应 noop
    assert jump_marker_callback(ctx, _text_response("再打开")) is None


def test_callback_noop_for_function_call_response():
    ctx = _ctx(state={"pending_jump": "punch-details"})
    # 含 function_call 的 part（模型还在调工具，不是最终文本）
    part = SimpleNamespace(text=None, function_call=SimpleNamespace(name="page_jump"))
    resp = SimpleNamespace(content=SimpleNamespace(parts=[part]))
    assert jump_marker_callback(ctx, resp) is None
    # state 不清除（等最终文本再注入）
    assert "pending_jump" in ctx.state
