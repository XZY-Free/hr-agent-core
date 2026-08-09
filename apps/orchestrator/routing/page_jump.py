"""页面跳转工具：13 类码表校验，成功时把 permissionCode 写入 state.pending_jump。

标记注入由 callbacks/jump_marker.py 在 after_model_callback 中完成（不依赖模型自觉输出）。
"""
from packages.hr_domain.schemas.tool_result import ok, err
from packages.hr_domain.constants.page_codes import PAGE_CODES


def page_jump(page_name: str, tool_context) -> dict:
    """登记页面跳转意图。page_name 必须是 PAGE_CODES 的 key。

    Args:
        page_name: 跳转意图名（如"打卡明细"）
    """
    if page_name not in PAGE_CODES:
        # 附上可选页面，让模型能自我纠正（换说法重试），而不是把失败甩给用户
        choices = "、".join(PAGE_CODES)
        return err("unknown_page", f"未知的页面：{page_name}。可跳转的页面有：{choices}")
    code = PAGE_CODES[page_name]
    tool_context.state["pending_jump"] = code
    return ok({"page": page_name, "code": code})
