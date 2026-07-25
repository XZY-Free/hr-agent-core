"""after_model_callback：把 pending_jump 注入为 `[[JUMP:<code>]]` 文本标记。

模型只负责决定调 page_jump 与生成话术；标记由本回调以代码方式追加到最终文本末尾，
确保前端能稳定正则识别 `[[JUMP:([a-z-]+)]]` 后剥离并跳页。
"""


def jump_marker_callback(callback_context, llm_response):
    """ADK after_model_callback。返回 None 表示不修改；返回 LlmResponse 表示替换。"""
    state = callback_context.state
    code = state.get("pending_jump")
    if not code:
        return None

    content = getattr(llm_response, "content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    if not parts:
        return None

    # 含 function_call part 时模型还在调工具，不是最终文本——等下一轮
    if any(getattr(p, "function_call", None) is not None for p in parts):
        return None

    # 找最后一个文本 part 追加标记
    last_text_part = None
    for p in parts:
        if getattr(p, "text", None) is not None:
            last_text_part = p
    if last_text_part is None:
        return None

    last_text_part.text = last_text_part.text + f"\n[[JUMP:{code}]]"
    state.pop("pending_jump", None)
    return llm_response
