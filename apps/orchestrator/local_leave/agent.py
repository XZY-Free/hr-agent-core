"""当前单Runtime中的本地请假Agent构建入口。"""

from datetime import date

from veadk import Agent

from apps.orchestrator.local_leave.draft_tools import (
    confirm_leave_draft,
    save_leave_draft,
)
from apps.orchestrator.local_leave.prompts import LEAVE_AGENT_PROMPT


def build_leave_agent(*, model_name: str, model_extra_config: dict) -> Agent:
    """构造本地请假Agent：模型只能通过 save_leave_draft/confirm_leave_draft 表达请求。

    不再向模型暴露 request_user_input：缺槽位/零值/校验都由权威 DraftResult 裁决，模型不能
    旁路绕过草稿，追问也来自领域返回。强制 tool_choice=required（拷贝 model_extra_config
    覆盖，不影响 root/Consult）、parallel_tool_calls=False，并禁止向 peer 转交。保留 parent
    transferability 供 ADK 在下一轮确定性续接最后响应的 leave_agent。
    """
    today = date.today().isoformat()
    leave_model_config = dict(model_extra_config or {})
    leave_model_config["tool_choice"] = "required"
    leave_model_config["parallel_tool_calls"] = False
    return Agent(
        name="leave_agent",
        model_name=model_name,
        model_extra_config=leave_model_config,
        description="请假办理专员：受理请假申请、补齐信息、校验并提交请假单",
        instruction=LEAVE_AGENT_PROMPT.format(today=today),
        tools=[save_leave_draft, confirm_leave_draft],
        disallow_transfer_to_peers=True,
    )
