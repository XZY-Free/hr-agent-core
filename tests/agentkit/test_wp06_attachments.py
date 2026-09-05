"""WP-06 附件/文档上下文远端验收：一个连续的业务流。

一个带附件的公共 A2A 请求要么在模型猜测前以精确附件错误明确失败（fail closed），
要么有效的「已解析 DocumentContext」必须被已部署 Consult 运行时对每个被引用文档真实消费。

范围：真实 HTTPS A2A 调用（AgentKit 开发 Runtime 的 orchestrator 与 consult）。
无本地应用/模型/服务、无 fake-model、无 ASGI、无 mock、无 localhost 服务；
不 import apps/packages/veadk；不 skip/xfail；不打印主体/oracle/响应正文/answer/凭据。

当前验收部署：Orchestrator v28、Consult v12。本文件只在头注记录版本，不做版本硬断言；
结论由云端执行裁决。公共附件错只用公共可观察的结构化字段 status / result_type /
error_code 断言；Consult 文档结果只用 status / question_category / answer。
协议/网络失败必须让测试直接失败（request_task/request_continuation 收敛为
AcceptanceError），绝不当作预期业务拒绝。

设计目标（冻结行为）：
- 公共无 resolver（空真实 AttachmentResolver registry）：1 或 5 个支持引用 =>
  attachment_not_resolvable；不支持 resource_type => attachment_type_not_supported；
  6 个引用 => attachment_limit_exceeded；本地路径/file:// 引用 => contract_error。
- 仅附件空白文本 => input_required/needs clarification，不向模型推断内容。
- DocumentContext 线格式 = 前缀 hr-document-v1: + 紧凑 JSON {"documents":[...]}；
  每项必填 canonical_reference，可选 display_name/media_type/url/content；
  至少一个安全 http(s) url 或非空已净化 content；最多 5 项、单项 content<=30k。
- TEXT-only 文档 = canonical_reference + content（不伪造 url）；URL-only 文档 = url
  且无占位 content，Consult 必须真实下载；多文档必须全部到达 Consult。
- 新任务/新会话（空 context_summary）不得回答先前文档的唯一事实。
- 敏感/本地回环 DocumentContext 必须拒绝/fail closed，绝不高亮源文本或回显。

对当前部署的预期：build_runtime 未注入 attachment_resolver，故 type/count/attachment-only
都无法区分而一律 attachment_not_resolvable（type/count/attachment-only 应 RED）；
DocumentContext 当前只支持单个 {url, content}，无法承载 {"documents":[...]} 线格式，
故 TEXT/URL/多文档/隔离用例应 RED；contract_error 与 fail-closed 与省略附件可能 GREEN。

安全：所有布尔断言走 business_support._check()，避免 pytest 断言内省打印主体/oracle/
响应正文/answer/敏感 token/凭据；响应递归检查不含 employee_id/secret/token 字段或子串。
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from tests.agentkit import business_support as bs
from tests.agentkit.business_support import OracleSubject

MARK = pytest.mark.agentkit

# 公共附件边界值：不支持的来源类型与数量上限。
_UNSUPPORTED_RESOURCE_TYPE = "ftp_document"
_ATTACHMENT_LIMIT_EXCEEDED_COUNT = 6
_CONSULT_LEGAL_STATUSES = frozenset({
    "succeeded", "need_more_information", "not_found", "rejected",
    "temporarily_unavailable", "failed",
})
# 敏感/凭据子串（只用于 fail-closed 判定，真实值由云端持有，不在此回显）。
_FORBIDDEN_TOKENS = ("employee_id", "secret", "token")
_DOC_PREFIX = "hr-document-v1:"

# 唯一、非机密、nonce 形态的用户输入文档事实（不是 fake 服务，只是输入数据）。
_FACT_TEXT = f"WP06-TEXT-{uuid4().hex[:8].upper()}"
_FACT_A = f"WP06-A-{uuid4().hex[:8].upper()}"
_FACT_B = f"WP06-B-{uuid4().hex[:8].upper()}"
_FACT_ISO = f"WP06-ISO-{uuid4().hex[:8].upper()}"
# 仅用于 URL 下载验证的公开稳定文档：RFC 5737 首个示例网络段前缀。
_RFC_URL = "https://www.rfc-editor.org/rfc/rfc5737.txt"
_RFC_PREFIX = "192.0.2"
# 本地回环/敏感输入：只用于 fail-closed 验证，不对外回显。
_LOCALHOST_URL = "http://localhost/private.txt"


# --------------------------------------------------------------------------
# fixtures（与 WP-01..05 一致：subject A 为 oracle 第一条主体）
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def identity_oracle() -> dict[str, OracleSubject]:
    return bs.load_identity_oracle()


@pytest.fixture(scope="session")
def subject_a(identity_oracle) -> OracleSubject:
    return list(identity_oracle.values())[0]


def _subject_payload(subject: OracleSubject) -> dict:
    return {"subject_id": subject.subject_id, "subject_kind": subject.subject_kind}


# --------------------------------------------------------------------------
# 消息构造
# --------------------------------------------------------------------------
def _attachment_ref(reference_id: str, resource_type: str = "web_document", **extra) -> dict:
    ref = {"reference_id": reference_id, "resource_type": resource_type}
    ref.update(extra)
    return ref


def _public_attachment_message(text: str, *, refs: list[dict], subject: OracleSubject):
    """构造公共 Orchestrator 消息：携带 attachment_references 元数据。"""
    return bs.orchestrator_message(
        text,
        execution_subject=_subject_payload(subject),
        extra_metadata={"attachment_references": refs},
    )


def _consult_message(subject: OracleSubject, text: str, *, context_summary: str = ""):
    """构造 Consult 内部可信 A2A 消息（caller_agent=hr_orchestrator，全新 session）。"""
    internal = bs.derive_internal_user_id(subject.subject_kind, subject.subject_id)
    return bs.employee_message(
        text, internal_user_id=internal, context_summary=context_summary
    )


def _doc_summary(*documents: dict) -> str:
    """编码冻结的 DocumentContext 线格式：hr-document-v1:{"documents":[...]}。"""
    payload = json.dumps(
        {"documents": list(documents)}, ensure_ascii=False, separators=(",", ":")
    )
    return _DOC_PREFIX + payload


def _text_doc(canonical_reference: str, content: str, **extra) -> dict:
    doc = {"canonical_reference": canonical_reference, "content": content}
    doc.update(extra)
    return doc


def _url_doc(canonical_reference: str, url: str, **extra) -> dict:
    doc = {"canonical_reference": canonical_reference, "url": url}
    doc.update(extra)
    return doc


# --------------------------------------------------------------------------
# 复用断言（均不打印主体/原始响应/answer/敏感 token/凭据；全部经 bs._check）
# --------------------------------------------------------------------------
def _assert_no_sensitive(obj, *, label: str) -> None:
    """递归断言响应不含 employee_id/secret/token 字段或子串。"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            bs._check(key not in _FORBIDDEN_TOKENS, f"{label}泄露敏感字段")
            _assert_no_sensitive(value, label=label)
    elif isinstance(obj, list):
        for value in obj:
            _assert_no_sensitive(value, label=label)
    elif isinstance(obj, str):
        for token in _FORBIDDEN_TOKENS:
            bs._check(token not in obj, f"{label}响应含敏感子串")


def _assert_truthy(answer, *, label: str) -> None:
    bs._check(isinstance(answer, str) and answer.strip(), f"{label}answer为空")


def _assert_attachment_failed(data: dict, error_code: str, *, label: str) -> None:
    """公共附件失败：status=failed、result_type=attachment、精确 error_code。"""
    bs._check(data.get("status") == "failed", f"{label}status非failed")
    bs._check(data.get("result_type") == "attachment", f"{label}result_type非attachment")
    bs._check(data.get("error_code") == error_code, f"{label}error_code非{error_code}")
    _assert_truthy(data.get("answer"), label=label)
    _assert_no_sensitive(data, label=label)


def _assert_attachment_contract(data: dict, *, label: str) -> None:
    """公共合同违规：结构化 failed + contract_error，绝不成功。"""
    bs._check(data.get("status") == "failed", f"{label}合同违规未判为failed")
    bs._check(data.get("error_code") == "contract_error", f"{label}error_code非contract_error")


def _assert_consult_succeeded(data: dict, *, label: str) -> None:
    bs._check(data.get("status") == "succeeded", f"{label}Consult未成功")
    bs._check(data.get("error_code") is None, f"{label}Consult成功携带非预期错误码")
    _assert_truthy(data.get("answer"), label=label)


def _assert_hr_document_category(data: dict, *, label: str) -> None:
    bs._check(
        data.get("question_category") == "hr_document",
        f"{label}question_category非hr_document",
    )


# --------------------------------------------------------------------------
# 公共边界：无 resolver 时 1/5 支持引用返回 attachment_not_resolvable（不伪造成功）。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 5])
async def test_public_supported_refs_fail_closed(probes, subject_a, count) -> None:
    refs = [_attachment_ref(f"ref-{i}", resource_type="web_document") for i in range(count)]
    data = await bs.request_task(
        probes, "orchestrator",
        _public_attachment_message("请帮我分析附件的政策内容", refs=refs, subject=subject_a),
    )
    _assert_attachment_failed(data, "attachment_not_resolvable", label=f"公共支持引用x{count}")


# --------------------------------------------------------------------------
# 公共边界：不支持 resource_type => attachment_type_not_supported。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_public_unsupported_type_fail_closed(probes, subject_a) -> None:
    refs = [_attachment_ref("ref-x", resource_type=_UNSUPPORTED_RESOURCE_TYPE)]
    data = await bs.request_task(
        probes, "orchestrator",
        _public_attachment_message("请分析这个附件的政策", refs=refs, subject=subject_a),
    )
    _assert_attachment_failed(data, "attachment_type_not_supported", label="公共不支持类型")


# --------------------------------------------------------------------------
# 公共边界：超过数量上限 => attachment_limit_exceeded。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_public_limit_exceeded(probes, subject_a) -> None:
    refs = [
        _attachment_ref(f"ref-{i}", resource_type="web_document")
        for i in range(_ATTACHMENT_LIMIT_EXCEEDED_COUNT)
    ]
    data = await bs.request_task(
        probes, "orchestrator",
        _public_attachment_message("请分析这些附件的政策", refs=refs, subject=subject_a),
    )
    _assert_attachment_failed(data, "attachment_limit_exceeded", label="公共超限")


# --------------------------------------------------------------------------
# 公共边界：本地路径/file:// 引用 => contract_error（结构化或 -32602），绝不成功。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize("ref_id", ["file:///etc/hosts", "../../etc/passwd", "/etc/hosts"])
async def test_public_contract_invalid_reference(probes, subject_a, ref_id) -> None:
    refs = [_attachment_ref(ref_id, resource_type="web_document")]
    data = await bs.request_task(
        probes, "orchestrator",
        _public_attachment_message("请分析附件", refs=refs, subject=subject_a),
    )
    _assert_attachment_contract(data, label="公共非法引用")


# --------------------------------------------------------------------------
# 公共边界：仅附件且空白文本 => input_required/needs clarification，不向模型推断内容。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_public_attachment_only_asks(probes, subject_a) -> None:
    refs = [_attachment_ref("ref-a", resource_type="web_document")]
    msg = _public_attachment_message("   ", refs=refs, subject=subject_a)
    outcome = await bs.request_continuation(probes, "orchestrator", msg)
    bs._check(not outcome.rejected, "附件-only被协议拒绝而非澄清追问")
    bs._check(outcome.category is None, "附件-only协议/网络失败")
    resp = outcome.response
    bs._check(resp is not None, "附件-only未返回结构化结果")
    data = resp.data
    # 冻结设计：input_required 追问，要求用户说明具体问题，绝不让模型猜内容。
    bs._check(data.get("status") == "input_required", "附件-only未映射为input_required")
    bs._check(data.get("result_type") == "missing_information", "附件-onlyresult_type非missing_information")
    bs._check(data.get("error_code") == "input_required", "附件-onlyerror_code非input_required")
    _assert_truthy(data.get("answer"), label="附件-only")
    _assert_no_sensitive(data, label="附件-only")


# --------------------------------------------------------------------------
# Consult happy path：单个 TEXT-only 文档的唯一事实被真实回答。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_consult_text_document_fact(probes, subject_a) -> None:
    summary = _doc_summary(_text_doc("doc-text-1", _FACT_TEXT))
    data = await bs.request_task(
        probes, "consult",
        _consult_message(subject_a, "请根据上传的文档，逐字告诉我文档里出现的唯一标记，不要改写。",
                         context_summary=summary),
    )
    _assert_consult_succeeded(data, label="TEXT文档")
    _assert_hr_document_category(data, label="TEXT文档")
    bs._check(_FACT_TEXT in data.get("answer", ""), "TEXT文档answer未含唯一事实")
    _assert_no_sensitive(data, label="TEXT文档")


# --------------------------------------------------------------------------
# Consult happy path：两个 TEXT-only 文档的全部唯一事实都被回答。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_consult_multiple_text_documents(probes, subject_a) -> None:
    summary = _doc_summary(
        _text_doc("doc-a", _FACT_A),
        _text_doc("doc-b", _FACT_B),
    )
    data = await bs.request_task(
        probes, "consult",
        _consult_message(subject_a, "请根据上传的两个文档，分别说出两个文档里各自的唯一标记，不要改写。",
                         context_summary=summary),
    )
    _assert_consult_succeeded(data, label="多TEXT文档")
    answer = data.get("answer", "")
    bs._check(_FACT_A in answer, "多TEXT文档answer未含文档A事实")
    bs._check(_FACT_B in answer, "多TEXT文档answer未含文档B事实")
    _assert_no_sensitive(data, label="多TEXT文档")


# --------------------------------------------------------------------------
# Consult URL-only：无占位 content，必须真实下载 RFC 5737，answer 含其示例前缀。
# URL 只来自 DocumentContext（_url_doc），不放在用户问题里，避免走既有纯消息 URL 行为。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_consult_url_only_downloads(probes, subject_a) -> None:
    summary = _doc_summary(_url_doc("doc-url-1", _RFC_URL))
    data = await bs.request_task(
        probes, "consult",
        _consult_message(
            subject_a,
            "请根据上传的文档，给出文档中出现的第一个示例网络地址前缀。",
            context_summary=summary,
        ),
    )
    _assert_consult_succeeded(data, label="URL-only")
    _assert_hr_document_category(data, label="URL-only")
    bs._check(_RFC_PREFIX in data.get("answer", ""), "URL-onlyanswer未含RFC5737前缀(占位)")
    _assert_no_sensitive(data, label="URL-only")


# --------------------------------------------------------------------------
# Consult 新任务隔离：带文档上下文的查询成功后，新会话/空上下文不得复述该唯一事实。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_consult_new_task_isolation(probes, subject_a) -> None:
    summary = _doc_summary(_text_doc("doc-iso", _FACT_ISO))
    first = await bs.request_task(
        probes, "consult",
        _consult_message(subject_a, "请根据上传的文档，逐字告诉我文档里出现的唯一标记。",
                         context_summary=summary),
    )
    _assert_consult_succeeded(first, label="隔离首询")
    bs._check(_FACT_ISO in first.get("answer", ""), "隔离首询answer未含唯一事实")

    # 全新 session（默认空 context_summary），不应继承上一任务的文档事实。
    second = await bs.request_task(
        probes, "consult",
        _consult_message(subject_a, "你之前提到过的那个唯一标记是什么？"),
    )
    bs._check(second.get("status") in _CONSULT_LEGAL_STATUSES, "隔离新会话status非法")
    bs._check(
        second.get("error_code") not in {
            "attachment_not_resolvable", "attachment_type_not_supported",
            "attachment_limit_exceeded", "contract_error", "needs_clarification",
        },
        "隔离新会话出现附件类错误码",
    )
    bs._check(
        _FACT_ISO not in second.get("answer", ""),
        "新会话错误复述了先前的文档事实",
    )
    _assert_no_sensitive(second, label="隔离新会话")


# --------------------------------------------------------------------------
# 敏感/本地回环 DocumentContext：必须 fail-closed，绝不高亮源文本或回显。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "summary,echo_tokens",
    [
        (
            _doc_summary(_text_doc("doc-secret", "示例内容含 client_secret 关键字以触发敏感拒绝")),
            ("client_secret",),
        ),
        (
            _doc_summary(_url_doc("doc-lh", _LOCALHOST_URL)),
            ("localhost", "private.txt"),
        ),
    ],
)
async def test_consult_sensitive_invalid_fail_closed(probes, subject_a, summary, echo_tokens) -> None:
    msg = _consult_message(subject_a, "请根据文档告诉我里面的唯一标记。", context_summary=summary)
    outcome = await bs.request_continuation(probes, "consult", msg)
    # 协议层 -32602 拒绝（凭据类）属合法 fail-closed；结构化 failed（本地回环）亦合法。
    if outcome.rejected:
        return
    bs._check(outcome.category is None, "敏感/本地回环协议或网络失败")
    resp = outcome.response
    bs._check(resp is not None, "敏感/本地回环未返回结构化结果")
    data = resp.data
    bs._check(data.get("status") != "succeeded", "敏感/本地回环不应成功")
    _assert_truthy(data.get("answer"), label="敏感/本地回环")
    _assert_no_sensitive(data, label="敏感/本地回环")
    # 绝不高亮源文本或回显本地/敏感子串。
    rendered = json.dumps(data, ensure_ascii=False)
    for token in echo_tokens:
        bs._check(token not in rendered, f"敏感/本地回环回显了{token}")


# --------------------------------------------------------------------------
# 省略附件：普通 Consult 请求返回合法的非附件结果，不要求特定 LLM 措辞。
# --------------------------------------------------------------------------
@MARK
@pytest.mark.asyncio
async def test_consult_omitted_attachments_ordinary(probes, subject_a) -> None:
    data = await bs.request_task(
        probes, "consult",
        _consult_message(subject_a, "我们公司的年假制度是怎么规定的？"),
    )
    bs._check(data.get("status") in _CONSULT_LEGAL_STATUSES, "省略附件status非法")
    bs._check(data.get("question_category") != "hr_document", "省略附件被误判为文档")
    bs._check(data.get("error_code") not in {
        "attachment_not_resolvable", "attachment_type_not_supported",
        "attachment_limit_exceeded", "contract_error", "needs_clarification",
    }, "省略附件出现附件类错误码")
    _assert_truthy(data.get("answer"), label="省略附件")
    _assert_no_sensitive(data, label="省略附件")
