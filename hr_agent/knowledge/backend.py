"""KnowledgeBackend 抽象层与工厂。"""

import os
from pathlib import Path
from typing import Protocol


class KnowledgeBackend(Protocol):
    """知识库检索后端协议。"""

    def search(self, query: str, scope: str, top_k: int = 5) -> list[dict]:
        """
        检索知识库。

        Args:
            query: 查询文本
            scope: 检索范围（policy / handbook / salary / childcare / all）
            top_k: 返回条数上限

        Returns:
            按相关性排序的检索结果列表，每项为 dict:
            {"content": str, "source": str, "score": float}
        """
        ...


def get_backend() -> KnowledgeBackend:
    """工厂函数：根据 KB_BACKEND 环境变量返回对应后端实例。"""
    backend_type = os.getenv("KB_BACKEND", "stub")
    if backend_type == "stub":
        from hr_agent.knowledge.local_stub import LocalStubBackend

        return LocalStubBackend()
    raise ValueError(f"未知的 KB_BACKEND: {backend_type}")
