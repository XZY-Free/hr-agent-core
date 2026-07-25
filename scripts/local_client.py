"""本地联调 client：对齐 ADK 官方会话协议，验证两个首验证项。

用法（需先 `uv run python agent.py` 起服务，并在 .env 配置真实方舟模型 Key）：
    uv run python scripts/local_client.py --base-url http://localhost:8000

两个首验证项：
  ① 工具能从 state 读到业务变量（观察服务日志中盖亚请求发出 / SSE 流中出现余额话术）
  ② SSE 最终文本含完整 `[[JUMP:punch-details]]`

若 Runtime 不支持建会话传 state，改用备选方案：在 AgentkitAgentServerApp 前加 FastAPI 中间件，
从请求头 X-Biz-Vars 解析变量写入 session state（详见 deploy/README.md）。
"""
import argparse
import json
import sys
from typing import Any

import requests

DEFAULT_BASE = "http://localhost:8000"
APP_NAME = "root_agent"  # 与 agent.py 中 root_agent.name 一致
USER_ID = "local-debug-user"


def _post_json(base_url: str, path: str, body: dict[str, Any]) -> dict:
    resp = requests.post(f"{base_url}{path}", json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def create_session(base_url: str, session_id: str, state: dict[str, Any]) -> dict:
    """创建会话并写入业务变量到 state。

    ADK 协议：POST /apps/{app}/users/{user}/sessions，body 可带 state。
    """
    return _post_json(
        base_url,
        f"/apps/{APP_NAME}/users/{USER_ID}/sessions",
        {"session_id": session_id, "state": state},
    )


def run_sse(base_url: str, session_id: str, text: str,
            state_delta: dict[str, Any] | None = None) -> str:
    """发消息并以 SSE 流方式收集最终文本。

    返回所有文本 part 拼接（用于断言关键词与 JUMP 标记）。
    """
    body: dict[str, Any] = {
        "app_name": APP_NAME,
        "user_id": USER_ID,
        "session_id": session_id,
        "new_message": {"role": "user", "parts": [{"text": text}]},
        "streaming": True,
    }
    if state_delta:
        body["state_delta"] = state_delta

    final_text_parts: list[str] = []
    with requests.post(
        f"{base_url}/run_sse", json=body, stream=True, timeout=120
    ) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            payload = raw[len("data:"):].strip()
            if not payload:
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            # ADK SSE 事件结构：{"content": {"parts": [...]}, ...}
            content = event.get("content") or {}
            for p in content.get("parts", []):
                if "text" in p and p["text"]:
                    final_text_parts.append(p["text"])
    return "\n".join(final_text_parts)


def verify(base_url: str, biz_vars: dict[str, Any]) -> int:
    session_id = "local-debug-session"
    print(f"[1/3] 创建会话 session_id={session_id}，注入业务变量…")
    try:
        create_session(base_url, session_id, biz_vars)
        print("     会话创建成功。")
    except Exception as e:
        print(f"     会话创建失败：{e}", file=sys.stderr)
        print(
            "     若 Runtime 不支持建会话传 state，参见 deploy/README.md 的备选方案。",
            file=sys.stderr,
        )
        return 1

    print("[2/3] 验证①：发消息「我还有几天年假？」观察工具能否读到 state…")
    text1 = run_sse(base_url, session_id, "我还有几天年假？")
    print(f"     回复：{text1!r}")
    # 验证①判定：回复中应出现余额数字（来自盖亚接口），或服务日志中出现盖亚请求
    if not text1:
        print("     ⚠ 未收到回复文本——检查服务日志中盖亚请求是否发出。")
        return 1
    print("     ✓ 已收到回复，请人工确认服务日志中盖亚请求已发出（含 Bearer JWT）。")

    print("[3/3] 验证②：发消息「打开打卡明细」验证 JUMP 标记…")
    text2 = run_sse(base_url, session_id, "打开打卡明细")
    print(f"     回复：{text2!r}")
    if "[[JUMP:punch-details]]" not in text2:
        print("     ✗ 未在 SSE 最终文本中找到 [[JUMP:punch-details]] 标记。")
        return 1
    print("     ✓ 验证②通过：SSE 最终文本含完整 [[JUMP:punch-details]]。")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--employee-id", default="E001")
    parser.add_argument("--corp-id", default="corp1")
    parser.add_argument("--client-secret", default="sec")
    parser.add_argument("--grant-type", default="client_credentials")
    args = parser.parse_args()

    biz_vars = {
        "employeeId": args.employee_id,
        "corp_id": args.corp_id,
        "client_secret": args.client_secret,
        "grant_type": args.grant_type,
    }
    sys.exit(verify(args.base_url, biz_vars))


if __name__ == "__main__":
    main()
