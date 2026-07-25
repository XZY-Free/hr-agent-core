"""页面跳转工具：13 类码表校验，成功时把 permissionCode 写入 state.pending_jump。

标记注入由 callbacks/jump_marker.py 在 after_model_callback 中完成（不依赖模型自觉输出）。
"""
from hr_agent.schemas.tool_result import ok, err
from hr_agent.constants.page_codes import PAGE_CODES


def page_jump(page_name: str, tool_context) -> dict:
    """登记页面跳转意图。page_name 必须是 PAGE_CODES 的 key。

    Args:
        page_name: 跳转意图名（如"打卡明细"）
    """
    if page_name not in PAGE_CODES:
        return err("unknown_page", f"未知的页面：{page_name}")
    code = PAGE_CODES[page_name]
    tool_context.state["pending_jump"] = code
    return ok({"page": page_name, "code": code})
