"""parse_document 工具测试。"""
from pathlib import Path

import pytest
import responses

from apps.consult_agent.tools.parse_document import parse_document


class FakeContext:
    state = {}


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@responses.activate
def test_parse_document_success():
    ctx = FakeContext()
    md_bytes = (FIXTURES_DIR / "notice.md").read_bytes()
    responses.add(
        responses.GET,
        "https://example.com/notice.md",
        body=md_bytes,
        status=200,
        content_type="text/markdown",
    )
    r = parse_document("https://example.com/notice.md", tool_context=ctx)
    assert r["success"] is True
    assert "三楼大会议室" in r["data"]["text"]
    assert r["data"]["truncated"] is False


@responses.activate
def test_parse_document_file_too_large():
    ctx = FakeContext()
    responses.add(
        responses.GET,
        "https://example.com/big.docx",
        body=b"x",
        status=200,
        headers={"Content-Length": "30000000"},
    )
    r = parse_document("https://example.com/big.docx", tool_context=ctx)
    assert r["success"] is False
    assert r["error_type"] == "file_too_large"


@responses.activate
def test_parse_document_download_failed():
    ctx = FakeContext()
    responses.add(
        responses.GET,
        "https://example.com/missing.docx",
        status=404,
    )
    r = parse_document("https://example.com/missing.docx", tool_context=ctx)
    assert r["success"] is False
    assert r["error_type"] == "parse_failed"
    assert "链接有效" in r["message"]


def test_parse_document_rejects_non_http():
    ctx = FakeContext()
    r = parse_document("ftp://example.com/file.docx", tool_context=ctx)
    assert r["success"] is False
    assert r["error_type"] == "parse_failed"
