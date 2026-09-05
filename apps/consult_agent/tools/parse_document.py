"""COS 文档解析工具：下载并提取文本。

跨 Runtime 已解析的文档以 `{"documents":[...]}` envelope 绑定到当前 A2A turn：
- 若命中一个绑定文档且其 content 非空 → 直接返回该精确内容，不再网络下载；
- 若命中一个绑定文档但为 URL-only（无 content）→ 落入真实 HTTP 下载/MarkItDown 路径；
- 未命中任何绑定文档 → 走真实下载路径；
- 非 http(s)/带凭据/本地回环 → 在访问网络前直接拒绝。
"""

import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlparse

import requests
from markitdown import MarkItDown

from packages.hr_domain.schemas.tool_result import ok, err

_MAX_SIZE = 20 * 1024 * 1024  # 20MB
_MAX_TEXT_LEN = 30000
_DOCUMENT_CONTEXT: ContextVar[dict | None] = ContextVar(
    "consult_document_context", default=None
)

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


@contextmanager
def bind_document_context(context: dict | None):
    """Bind one sanitized document envelope ({"documents":[...]}) to the turn."""
    token = _DOCUMENT_CONTEXT.set(context)
    try:
        yield
    finally:
        _DOCUMENT_CONTEXT.reset(token)


def _matching_document(context, file_url: str) -> dict | None:
    """Return the bound document whose url exactly equals file_url, else None."""
    if not isinstance(context, dict):
        return None
    documents = context.get("documents")
    if not isinstance(documents, list):
        return None
    for doc in documents:
        if isinstance(doc, dict) and doc.get("url") == file_url:
            return doc
    return None


def _unsafe_url(parsed) -> bool:
    if parsed.username or parsed.password:
        return True
    host = (parsed.hostname or "").lower()
    if host in _LOOPBACK_HOSTS or host.endswith(".local"):
        return True
    return False


def parse_document(file_url: str, tool_context) -> dict:
    """下载 COS 文件并解析为文本。

    Args:
        file_url: http(s) 文件地址
        tool_context: ADK 工具上下文
    """
    parsed = urlparse(file_url)
    if parsed.scheme not in ("http", "https"):
        return err("parse_failed", "文档下载或解析失败，请确认链接有效")
    if _unsafe_url(parsed):
        return err("parse_failed", "文档下载或解析失败，请确认链接有效")

    supplied = _DOCUMENT_CONTEXT.get()
    match = _matching_document(supplied, file_url)
    if match is not None:
        text = match.get("content")
        if isinstance(text, str) and text:
            truncated = len(text) > _MAX_TEXT_LEN
            if truncated:
                text = text[:_MAX_TEXT_LEN] + "（文档过长，已截断）"
            return ok({"text": text, "truncated": truncated})
        # URL-only（或空 content）：不返回 parse_failed，落入真实下载路径。

    try:
        resp = requests.get(file_url, timeout=30, stream=True)
        resp.raise_for_status()
    except Exception:
        return err("parse_failed", "文档下载或解析失败，请确认链接有效")

    # 检查 Content-Length
    content_length = resp.headers.get("Content-Length")
    if content_length is not None and int(content_length) > _MAX_SIZE:
        return err("file_too_large", "文件超过 20MB，无法解析")

    # 流式读取并限制大小
    try:
        data = b""
        for chunk in resp.iter_content(chunk_size=8192):
            data += chunk
            if len(data) > _MAX_SIZE:
                return err("file_too_large", "文件超过 20MB，无法解析")
    except Exception:
        return err("parse_failed", "文档下载或解析失败，请确认链接有效")

    # 写入临时文件
    suffix = Path(parsed.path).suffix or ".tmp"
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(data)
            tmp_path = f.name
    except Exception:
        return err("parse_failed", "文档下载或解析失败，请确认链接有效")

    # 用 markitdown 解析
    try:
        md = MarkItDown()
        result = md.convert(tmp_path)
        text = result.text_content or ""
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        return err("parse_failed", "文档下载或解析失败，请确认链接有效")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    truncated = False
    if len(text) > _MAX_TEXT_LEN:
        text = text[:_MAX_TEXT_LEN] + "（文档过长，已截断）"
        truncated = True

    return ok({"text": text, "truncated": truncated})
