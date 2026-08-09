"""咨询应用Knowledge的公开结果与错误类型。"""

from typing import Protocol


class KnowledgeBackendError(RuntimeError):
    """不泄露SDK原始异常的Knowledge领域错误。"""

    def __init__(self, error_type: str):
        self.error_type = error_type
        super().__init__("知识库调用失败")


class KnowledgeSearchResults(list[dict]):
    """保持结果列表契约，并携带聚合检索的失败scope。"""

    def __init__(self, items=(), *, failed_scopes=()):
        super().__init__(items)
        self.failed_scopes = tuple(failed_scopes)

    @property
    def partial_failure(self) -> bool:
        return bool(self.failed_scopes)


class KnowledgeBackend(Protocol):
    """知识库检索后端协议。"""

    def search(
        self, query: str, scope: str, top_k: int = 5
    ) -> list[dict] | KnowledgeSearchResults:
        """返回包含content、source、score的检索结果。"""
        ...
