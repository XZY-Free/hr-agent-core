"""主 Agent 结构测试：验证 sub_agents / tools / after_model_callback 挂载正确。

不调用真实模型，仅做结构断言（与 leave_agent 测试同构）。
"""
from hr_agent.agents.main_agent import root_agent
from hr_agent.agents.leave_agent import leave_agent
from hr_agent.agents.consult_agent import consult_agent
from hr_agent.callbacks.jump_marker import jump_marker_callback


def _tool_names(agent) -> set:
    return {getattr(t, "__name__", getattr(t, "name", "")) for t in agent.tools}


def test_root_agent_basic():
    assert root_agent.name == "root_agent"
    assert root_agent.model_name  # 默认 doubao-seed-1.6-250615 或由环境变量覆盖
    assert root_agent.instruction and "人力" in root_agent.instruction


def test_root_agent_has_two_sub_agents():
    sub_names = {getattr(a, "name", "") for a in root_agent.sub_agents}
    assert "leave_agent" in sub_names
    assert "consult_agent" in sub_names
    # 同一对象实例（不是副本）
    assert any(a is leave_agent for a in root_agent.sub_agents)
    assert any(a is consult_agent for a in root_agent.sub_agents)


def test_root_agent_tools_include_query_and_jump():
    names = _tool_names(root_agent)
    expected = {"page_jump", "get_leave_balance", "get_medical_period", "calc_annual_leave"}
    assert expected <= names


def test_root_agent_mounts_jump_marker_callback():
    cb = root_agent.after_model_callback
    if isinstance(cb, list):
        assert jump_marker_callback in cb
    else:
        assert cb is jump_marker_callback


def test_main_prompt_phrases_injected():
    """MAIN_AGENT_PROMPT.format(**PHRASES) 后应包含话术原文，且不再有未替换占位符。"""
    instruction = root_agent.instruction
    assert "{cancel_leave}" not in instruction
    assert "{handoff}" not in instruction
    assert "{consult_not_ready}" not in instruction
    # 话术关键短语已被注入
    assert "我的表单" in instruction  # 来自 PHRASES["cancel_leave"]
    assert "转人工" in instruction
    # 二期上线后不再引用"敬请期待"
    assert "敬请期待" not in instruction
    assert "consult_agent" in instruction
