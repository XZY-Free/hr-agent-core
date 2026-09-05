"""保留现有 Agent/Session，只把 Runner 事件投影为明确的回合结果。

WP-02：同 (user_id, task session) 需串行执行（session 创建 + 整轮 run 均在锁内），避免
同一草稿被并发读写（lost update）；且收到真实草稿工具 function_response 后立即结束本
次 run（SDK 事件已持久化，root 已核实），不再让 LLM 在本轮继续伪确认或改写权威数字。
纯结构化草稿（无文本）也是有效回合，不抛 ValueError；普通 Consult / WP01 行为不变。
"""

import asyncio
import os
from contextlib import aclosing

from google.adk.agents.run_config import RunConfig
from google.genai import types

from packages.agent_runtime.user_input import TurnOutput


class PublicLocalRunner:
    def __init__(self, runner):
        self.runner = runner
        # 按 (user_id, task session) 串行锁；不同 task/会话不互相阻塞。
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def _lock_for(self, user_id: str, session_id: str) -> asyncio.Lock:
        key = (user_id, session_id)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def run(self, *, messages: str, user_id: str, session_id: str) -> TurnOutput:
        lock = self._lock_for(user_id, session_id)
        async with lock:
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
                    # 权威身份失败或已得到结构化草稿结果：立即停止，不再消费后续事件，
                    # 避免被本回合 LLM 文本/伪确认改写权威数字。
                    if output.terminal_error_code is not None or output.leave_draft is not None:
                        break
        # 纯结构化草稿（无 answer 文本）是有效回合结果；仅当既无文本也无草稿结构才报错。
        if not output.answer and output.leave_draft is None and output.terminal_error_code is None:
            raise ValueError("智能体未返回回答或补充信息请求")
        return output
