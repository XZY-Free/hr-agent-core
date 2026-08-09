"""KnowledgeBackend 抽象层与工厂。"""

import os

from apps.consult_agent.knowledge.types import (
    KnowledgeBackend,
    KnowledgeBackendError,
    KnowledgeSearchResults,
)


def get_backend() -> KnowledgeBackend:
    """工厂函数：根据 KB_BACKEND 环境变量返回对应后端实例。"""
    backend_type = os.getenv("KB_BACKEND", "stub")
    if backend_type == "stub":
        from apps.consult_agent.knowledge.local_stub import LocalStubBackend

        return LocalStubBackend()
    if backend_type == "agentkit":
        from apps.consult_agent.knowledge.agentkit_backend import AgentKitKnowledgeBackend

        return AgentKitKnowledgeBackend()
    raise ValueError(f"未知的 KB_BACKEND: {backend_type}")
