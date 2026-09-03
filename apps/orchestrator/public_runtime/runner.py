"""保留现有 Agent/Session，只把 Runner 事件投影为明确的回合结果。"""

import os
from contextlib import aclosing

from google.adk.agents.run_config import RunConfig
from google.genai import types

from packages.agent_runtime.user_input import TurnOutput


class PublicLocalRunner:
    def __init__(self, runner):
        self.runner = runner

    async def run(self, *, messages: str, user_id: str, session_id: str) -> TurnOutput:
        await self.runner.short_term_memory.create_session(
            app_name=self.runner.app_name, user_id=user_id, session_id=session_id,
        )
        output = TurnOutput()
        async with aclosing(self.runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=messages)]),
            run_config=RunConfig(max_llm_calls=int(os.getenv("MODEL_AGENT_MAX_LLM_CALLS", "100"))),
        )) as events:
            async for event in events:
                output.observe(event)
        if not output.answer:
            raise ValueError("智能体未返回回答或补充信息请求")
        return output
