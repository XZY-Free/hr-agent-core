"""AgentKit Knowledge 真实后端占位。"""

import os


class AgentKitKnowledgeBackend:
    """AgentKit 知识库检索后端（待接入）。

    collection_map 为 scope → AgentKit 知识库 ID 映射，
    从环境变量 KB_COLLECTION_POLICY/HANDBOOK/SALARY/CHILDCARE 读取。
    """

    def __init__(self, collection_map: dict[str, str] | None = None):
        if collection_map is None:
            collection_map = {
                "policy": os.getenv("KB_COLLECTION_POLICY", ""),
                "handbook": os.getenv("KB_COLLECTION_HANDBOOK", ""),
                "salary": os.getenv("KB_COLLECTION_SALARY", ""),
                "childcare": os.getenv("KB_COLLECTION_CHILDCARE", ""),
            }
        self.collection_map = collection_map

    def search(self, query: str, scope: str, top_k: int = 5) -> list[dict]:
        raise NotImplementedError(
            "AgentKit 知识库待接入：需库 ID 与检索 API 核验，见 docs/CHECKLIST.md"
        )
