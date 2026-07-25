from hr_agent.agents.leave_agent import leave_agent


def test_leave_agent_wiring():
    assert leave_agent.name == "leave_agent"
    tool_names = {getattr(t, "__name__", getattr(t, "name", "")) for t in leave_agent.tools}
    assert {"get_leave_permissions", "get_leave_balance", "get_schedule", "submit_leave"} <= tool_names


def test_leave_agent_has_instruction_and_model():
    assert leave_agent.instruction and "请假" in leave_agent.instruction
    assert leave_agent.model_name  # 默认 doubao-seed-1.6-250615 或由环境变量覆盖
