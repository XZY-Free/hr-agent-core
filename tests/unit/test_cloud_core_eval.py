from scripts.cloud_core_eval import _inferred_remote_tools


def test_cloud_consult_document_route_records_parse_document_not_kb_search():
    remote = {"target": "hr-consult-agent", "status": "succeeded"}

    assert _inferred_remote_tools(
        remote, "https://example.com/notice.docx 这份文件说了什么"
    ) == ["parse_document"]


def test_cloud_consult_policy_route_records_kb_search():
    remote = {"target": "hr-consult-agent", "status": "succeeded"}

    assert _inferred_remote_tools(remote, "迟到扣款制度是什么") == ["kb_search"]
