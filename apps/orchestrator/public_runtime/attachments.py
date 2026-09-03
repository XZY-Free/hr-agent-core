"""公共附件解析边界：AttachmentReference → AttachmentResolver → ResolvedAttachment。

目标（WP-06）：对 hr-agent-core 当前公共合同做到"能解析就安全解析，不能解析就明确
失败，绝不静默忽略"。本轮不改 SnowHarness、不伪造解析能力；无外部 resolver 时返回
attachment_not_resolvable。ResolvedAttachment 是安全对象，禁止 local path / credential /
file:// / 用户可控内部 URL。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from apps.orchestrator.public_runtime.request import AttachmentReference


class AccessMode(str, Enum):
    TEXT = "text"
    URL = "url"


class AttachmentResolutionError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class ResolvedAttachment:
    canonical_reference: str
    resource_type: str
    media_type: str | None
    display_name: str | None
    access_mode: AccessMode
    url: str | None = None          # 仅当 access_mode=URL，且通过 SSRF/scheme 校验
    text: str | None = None         # 仅当 access_mode=TEXT，且通过 sensitive 扫描

    def to_payload(self) -> dict:
        """转换为 A2A DocumentContext 可用载荷（无本地路径/credential/全文泄露）。"""
        payload = {
            "canonical_reference": self.canonical_reference,
            "resource_type": self.resource_type,
            "media_type": self.media_type,
            "display_name": self.display_name,
            "access_mode": self.access_mode.value,
        }
        if self.url:
            payload["url"] = self.url
        if self.text:
            payload["text"] = self.text
        return payload


# 允许的 resource_type 白名单；不在表内 → attachment_type_not_supported。
_SUPPORTED_TYPES = frozenset({"web_document", "file", "document"})
# 限本地路径 / 内部网络 / credential 的 URL。
_SENSITIVE_PATTERN = re.compile(
    r"authorization\s*:|bearer\s+|client_secret|access_token|"
    r"api[-_]?key\s*[:=]|secret\s*[:=]",
    re.IGNORECASE,
)


class AttachmentResolver:
    """单一附件解析职责。

    resolvers: resource_type -> callable(reference) -> ResolvedAttachment
      （生产环境可按 resource_type 注入；本轮无外部 resolver，默认 fail closed）。
    """

    def __init__(self, resolvers: dict[str, callable] | None = None, *, max_count: int = 5):
        self._resolvers = resolvers or {}
        self.max_count = max_count

    def resolve_all(self, references: list[AttachmentReference] | None) -> list[ResolvedAttachment]:
        if not references:
            return []
        if len(references) > self.max_count:
            raise AttachmentResolutionError(
                "attachment_limit_exceeded",
                "附件数量超出上限，请一次最多上传 5 个附件。",
            )
        resolved = []
        for ref in references:
            resolved.append(self._resolve_one(ref))
        return resolved

    def _resolve_one(self, ref: AttachmentReference) -> ResolvedAttachment:
        if ref.resource_type not in _SUPPORTED_TYPES:
            raise AttachmentResolutionError(
                "attachment_type_not_supported",
                "当前附件来源类型暂不受支持。",
            )
        resolver = self._resolvers.get(ref.resource_type)
        if resolver is None:
            # 无外部 resolver：明确失败，绝不静默忽略 / 假装已读取。
            raise AttachmentResolutionError(
                "attachment_not_resolvable",
                "当前附件引用暂时无法读取，请提供可访问的文档链接或使用已支持的附件来源。",
            )
        attachment = resolver(ref)
        if not isinstance(attachment, ResolvedAttachment):
            raise AttachmentResolutionError(
                "attachment_invalid", "附件解析结果无效。"
            )
        self._validate(attachment)
        return attachment

    @staticmethod
    def _validate(attachment: ResolvedAttachment) -> None:
        if attachment.access_mode is AccessMode.URL:
            if not attachment.url:
                raise AttachmentResolutionError("attachment_invalid", "附件引用缺少可访问地址。")
            _validate_url(attachment.url)
        elif attachment.access_mode is AccessMode.TEXT:
            if attachment.text is None:
                raise AttachmentResolutionError("attachment_invalid", "附件引用缺少内容。")
            if _SENSITIVE_PATTERN.search(attachment.text):
                raise AttachmentResolutionError("attachment_sensitive", "附件包含敏感内容。")
            if len(attachment.text) > 30000:
                raise AttachmentResolutionError("attachment_too_large", "单个附件内容过大。")


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise AttachmentResolutionError("attachment_invalid", "附件链接仅支持 http/https。")
    if not parsed.netloc:
        raise AttachmentResolutionError("attachment_invalid", "附件链接无效。")
    if parsed.username or parsed.password:
        raise AttachmentResolutionError("attachment_invalid", "附件链接不得包含凭据。")
    if parsed.hostname in {"127.0.0.1", "localhost", "::1", "0.0.0.0"} or parsed.hostname.endswith(".local"):
        raise AttachmentResolutionError("attachment_invalid", "附件链接禁止指向本机或内网地址。")
    if _SENSITIVE_PATTERN.search(url):
        raise AttachmentResolutionError("attachment_sensitive", "附件链接包含敏感内容。")
