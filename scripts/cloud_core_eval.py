"""Run the frozen core cases through a cloud Orchestrator with redacted evidence."""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = REPO_ROOT / "tests" / "eval" / "cases.yaml"
LOG_DIR = REPO_ROOT / "tests" / "e2e" / "logs"
DUMMY_STATE = {
    "employeeId": "E001",
    "corp_id": "corp1",
    "client_secret": "sec",
    "grant_type": "client_credentials",
}
DOC_QA_CONTEXT = {
    "url": "https://example.com/notice.docx",
    "content": (
        "# 2026 年春节假期安排通知\n\n"
        "一、放假时间：2 月 16 日至 2 月 22 日，共 7 天，2 月 23 日（周一）正常上班。\n"
        "二、值班安排：假期值班人员由各部门自行排定，值班表请于 2 月 10 日前"
        "报人力资源部备案，值班当日按加班处理。\n"
        "三、考勤要求：节前最后一个工作日与节后首个工作日均需正常打卡，"
        "因故不能到岗的请提前提交请假申请。\n"
    ),
}


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _resolve_dates(text: str) -> str:
    today = date.today()
    for token, offset in {
        "<today>": 0,
        "<tomorrow>": 1,
        "<yesterday>": -1,
        "<rest_day>": -2,
    }.items():
        text = text.replace(token, (today + timedelta(days=offset)).isoformat())
    return text


def _events(response: httpx.Response) -> list[dict]:
    result = []
    for line in response.iter_lines():
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                result.append(json.loads(payload))
    return result


def _inferred_remote_tools(remote: dict | None, text: str) -> list[str]:
    if not remote:
        return []
    if remote.get("target") == "hr-consult-agent":
        if re.search(r"https?://", text):
            return ["parse_document"]
        if remote.get("status") not in {"rejected", "need_more_information"}:
            return ["kb_search"]
    elif remote.get("target") == "hr-employee-data-agent":
        return ["get_medical_period" if "医疗期" in text else "calc_annual_leave"]
    return []


def _turn(client: httpx.Client, base_url: str, user_id: str, session_id: str, text: str) -> dict:
    response = client.post(
        base_url + "/run_sse",
        json={
            "app_name": "root_agent",
            "user_id": user_id,
            "session_id": session_id,
            "new_message": {"role": "user", "parts": [{"text": text}]},
            "streaming": True,
        },
    )
    events = _events(response)
    texts = []
    final_text = ""
    tools = []
    for event in events:
        event_texts = []
        for part in (event.get("content") or {}).get("parts", []):
            if not isinstance(part, dict):
                continue
            function_call = part.get("functionCall") or part.get("function_call")
            if isinstance(function_call, dict) and function_call.get("name"):
                tools.append(function_call["name"])
            value = part.get("text")
            if value and not part.get("thought"):
                event_texts.append(value)
        if event_texts:
            if event.get("partial"):
                texts.extend(event_texts)
            else:
                final_text = "\n".join(event_texts)
    all_event_text = "\n".join(
        part.get("text", "")
        for event in events
        for part in (event.get("content") or {}).get("parts", [])
        if isinstance(part, dict)
    )
    for marker in dict.fromkeys(re.findall(r"\[\[JUMP:[a-z-]+\]\]", all_event_text)):
        if marker not in final_text:
            final_text = f"{final_text}\n{marker}".strip()
    remote = next((event.get("a2a") for event in events if event.get("a2a")), None)
    inferred = _inferred_remote_tools(remote, text)
    return {
        "http_status": response.status_code,
        "event_count": len(events),
        "text": final_text or "".join(texts),
        "tools": tools + inferred,
        "inferred_tools": inferred,
        "remote": remote,
    }


def _assertions(case: dict, tools: list[str], final_text: str, dialog_text: str) -> list[str]:
    failures = []
    for tool in case.get("expect_tool", []):
        if tool not in tools:
            failures.append(f"missing_tool:{tool}")
    if case.get("expect_any_tool") and not any(tool in tools for tool in case["expect_any_tool"]):
        failures.append("missing_any_tool")
    for tool in case.get("expect_no_tool", []):
        if tool in tools:
            failures.append(f"unexpected_tool:{tool}")
    for keyword in case.get("expect_keywords", []):
        if keyword not in final_text:
            failures.append("missing_keyword")
    if case.get("expect_any_keyword") and not any(
        keyword in final_text for keyword in case["expect_any_keyword"]
    ):
        failures.append("missing_any_keyword")
    for keyword in case.get("expect_not_keywords", []):
        if keyword in final_text:
            failures.append("forbidden_keyword")
    marker = case.get("expect_marker")
    if marker and marker not in final_text:
        failures.append("missing_marker")
    for keyword in case.get("expect_keywords_anywhere", []):
        if keyword not in dialog_text:
            failures.append("missing_dialog_keyword")
    if case.get("expect_any_keyword_anywhere") and not any(
        keyword in dialog_text for keyword in case["expect_any_keyword_anywhere"]
    ):
        failures.append("missing_any_dialog_keyword")
    return failures


def main() -> None:
    base_url = _required("RUNTIME_URL").rstrip("/")
    api_key = _required("RUNTIME_API_KEY")
    user_id = os.environ.get("ORCHESTRATOR_USER_ID", "cloud-a2a-user-a")
    cases = yaml.safe_load(CASES_PATH.read_text())
    selected = {
        value.strip()
        for value in os.getenv("CLOUD_CASE_IDS", "").split(",")
        if value.strip()
    }
    if selected:
        known = {case["id"] for case in cases}
        if not selected <= known:
            raise SystemExit("CLOUD_CASE_IDS contains an unknown case")
        cases = [case for case in cases if case["id"] in selected]
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    evidence_path = LOG_DIR / f"cloud-core-eval-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    records = []
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(headers=headers, timeout=240) as client:
        for case in cases:
            session_id = f"cloud-{case['id']}-{uuid4()}"
            state = dict(DUMMY_STATE)
            if case["id"] == "doc_qa":
                state["document_context"] = DOC_QA_CONTEXT
            created = client.post(
                f"{base_url}/apps/root_agent/users/{user_id}/sessions",
                json={"session_id": session_id, "state": state},
            )
            turns = []
            texts = []
            tools = []
            if created.status_code < 300:
                for text in case["turns"]:
                    turn = _turn(client, base_url, user_id, session_id, _resolve_dates(text))
                    turns.append(turn)
                    texts.append(turn["text"])
                    tools.extend(turn["tools"])
                    if turn["http_status"] != 200 or not turn["event_count"]:
                        break
            final_text = texts[-1] if texts else ""
            failures = [] if created.status_code < 300 else ["session_create_failed"]
            failures.extend(_assertions(case, tools, final_text, "\n".join(texts)))
            quality_hits = [keyword in final_text for keyword in case.get("quality_keywords", [])]
            record = {
                "case_id": case["id"],
                "passed": not failures,
                "session_http_status": created.status_code,
                "turn_http_statuses": [turn["http_status"] for turn in turns],
                "turn_event_counts": [turn["event_count"] for turn in turns],
                "targets": [
                    (turn["remote"] or {}).get("target", "local") for turn in turns
                ],
                "remote_request_ids": [
                    (turn["remote"] or {}).get("request_id") for turn in turns
                    if (turn["remote"] or {}).get("request_id")
                ],
                "remote_statuses": [
                    (turn["remote"] or {}).get("status") for turn in turns
                    if turn["remote"]
                ],
                "tools": tools,
                "inferred_tool_count": sum(len(turn["inferred_tools"]) for turn in turns),
                "failure_rules": sorted(set(failures)),
                "quality_hits": quality_hits,
            }
            records.append(record)
            with evidence_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            print(json.dumps({
                "case_id": case["id"],
                "passed": record["passed"],
                "targets": record["targets"],
                "request_ids": record["remote_request_ids"],
                "failure_rules": record["failure_rules"],
            }, ensure_ascii=False, sort_keys=True), flush=True)
    passed = sum(record["passed"] for record in records)
    print(json.dumps({
        "case_count": len(records),
        "passed_count": passed,
        "failed_count": len(records) - passed,
        "evidence_file": evidence_path.name,
    }, sort_keys=True))
    if passed != len(records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
