"""当前单Runtime中的Orchestrator构建入口。"""

from datetime import date

from veadk import Agent

from apps.orchestrator.callbacks.jump_marker import jump_marker_callback
from apps.orchestrator.prompts import MAIN_AGENT_PROMPT
from apps.orchestrator.routing.page_jump import page_jump
from packages.hr_domain.constants.phrases import PHRASES


def build_orchestrator(
    *,
    model_name: str,
    model_extra_config: dict,
    leave_agent,
) -> Agent:
    """装配只保留Leave与固定本地能力的Orchestrator。"""
    today = date.today().isoformat()
    instruction = MAIN_AGENT_PROMPT.format(today=today, **PHRASES)
    return Agent(
        name="root_agent",
        model_name=model_name,
        model_extra_config=model_extra_config,
        description="人力 AI 助手入口：考勤请假分发、查询、页面跳转",
        instruction=instruction,
        tools=[page_jump],
        sub_agents=[leave_agent],
        after_model_callback=jump_marker_callback,
    )
