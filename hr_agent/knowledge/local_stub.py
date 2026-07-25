"""本地桩 KnowledgeBackend：基于 fixtures 关键词匹配。"""

from pathlib import Path


class LocalStubBackend:
    """按空段落切块，用查询字符 2-gram 命中数归一化打分。"""

    _SCOPE_FILES = {
        "policy": ["policy.md"],
        "handbook": ["handbook.md"],
        "salary": ["salary.md"],
        "childcare": ["childcare.md"],
        "all": ["policy.md", "handbook.md", "salary.md"],
    }

    def __init__(self, fixtures_dir: Path | None = None):
        if fixtures_dir is None:
            fixtures_dir = Path(__file__).parent / "fixtures"
        self._fixtures_dir = fixtures_dir
        self._chunks: list[dict] = []
        self._load_fixtures()

    def _load_fixtures(self):
        self._chunks = []
        for md_file in sorted(self._fixtures_dir.glob("*.md")):
            text = md_file.read_text(encoding="utf-8")
            # 按空行（两个及以上换行）分块
            raw_chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
            for chunk in raw_chunks:
                self._chunks.append({
                    "content": chunk,
                    "source": md_file.name,
                })

    def search(self, query: str, scope: str, top_k: int = 5) -> list[dict]:
        if scope not in self._SCOPE_FILES:
            return []
        allowed_sources = set(self._SCOPE_FILES[scope])
        query_chars = set(self._char_ngrams(query, n=2))
        if not query_chars:
            return []

        scored = []
        for chunk in self._chunks:
            if chunk["source"] not in allowed_sources:
                continue
            chunk_chars = set(self._char_ngrams(chunk["content"], n=2))
            hits = len(query_chars & chunk_chars)
            score = hits / len(query_chars) if query_chars else 0.0
            if score > 0:
                scored.append({
                    "content": chunk["content"],
                    "source": chunk["source"],
                    "score": round(score, 4),
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    @staticmethod
    def _char_ngrams(text: str, n: int = 2) -> list[str]:
        """字符级 n-gram。"""
        chars = list(text)
        if len(chars) < n:
            return []
        return ["".join(chars[i : i + n]) for i in range(len(chars) - n + 1)]
