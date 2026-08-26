"""Track H1/H2：端点Settings唯一Authority与Runtime Access Auth测试。"""

import pytest
from starlette.testclient import TestClient

from apps.orchestrator.public_a2a.settings import (
    DEFAULT_PORT,
    DEFAULT_PUBLIC_URL,
    PublicA2ASettings,
    SettingsError,
    normalize_public_base_url,
)


def test_settings_defaults():
    settings = PublicA2ASettings.from_env(env={})
    assert settings.listen_host == "127.0.0.1"
    assert settings.listen_port == DEFAULT_PORT == 8100
    assert settings.public_base_url == DEFAULT_PUBLIC_URL
    assert settings.auth_mode == "none"
    assert settings.card_url == "http://127.0.0.1:8100/"


def test_settings_custom_port_and_public_url():
    settings = PublicA2ASettings.from_env(
        env={
            "HR_ASSISTANT_A2A_PORT": "9123",
            "HR_ASSISTANT_A2A_PUBLIC_URL": "https://hr.example.com/",
        }
    )
    assert settings.listen_port == 9123
    assert settings.public_base_url == "https://hr.example.com"
    assert settings.card_url == "https://hr.example.com/"


def test_public_url_slash_normalization():
    assert normalize_public_base_url("http://127.0.0.1:8100///") == (
        "http://127.0.0.1:8100"
    )


@pytest.mark.parametrize(
    "bad_url",
    [
        "ftp://hr.example.com",
        "http://hr.example.com/?x=1",
        "http://hr.example.com/#frag",
        "hr.example.com:8100",
    ],
)
def test_public_url_invalid_rejected(bad_url):
    with pytest.raises(SettingsError):
        normalize_public_base_url(bad_url)
    with pytest.raises(SettingsError):
        PublicA2ASettings.from_env(
            env={"HR_ASSISTANT_A2A_PUBLIC_URL": bad_url}
        )
    # 空串视为未设置：normalize层拒绝，env层回退默认。
    with pytest.raises(SettingsError):
        normalize_public_base_url("")


def test_wildcard_listen_requires_explicit_public_url():
    """0.0.0.0监听不得自动作为advertised URL。"""
    with pytest.raises(SettingsError):
        PublicA2ASettings.from_env(
            env={"HR_ASSISTANT_A2A_HOST": "0.0.0.0"}
        )
    settings = PublicA2ASettings.from_env(
        env={
            "HR_ASSISTANT_A2A_HOST": "0.0.0.0",
            "HR_ASSISTANT_A2A_PUBLIC_URL": "https://hr.example.com",
        }
    )
    assert settings.listen_host == "0.0.0.0"
    assert settings.public_base_url == "https://hr.example.com"


def test_invalid_auth_mode_and_port_rejected():
    with pytest.raises(SettingsError):
        PublicA2ASettings.from_env(
            env={"HR_ASSISTANT_A2A_AUTH_MODE": "basic"}
        )
    with pytest.raises(SettingsError):
        PublicA2ASettings.from_env(env={"HR_ASSISTANT_A2A_PORT": "abc"})
    with pytest.raises(SettingsError):
        PublicA2ASettings.from_env(env={"HR_ASSISTANT_A2A_PORT": "70000"})


def test_bearer_mode_requires_token(monkeypatch):
    from apps.orchestrator.public_a2a import server as server_module

    class _Runtime:
        pass

    settings = PublicA2ASettings(
        listen_host="127.0.0.1",
        listen_port=8100,
        public_base_url="http://127.0.0.1:8100",
        auth_mode="bearer",
    )
    monkeypatch.delenv("HR_ASSISTANT_A2A_BEARER_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        server_module.build_public_a2a_app(runtime=_Runtime(), settings=settings)


def _jsonrpc_body():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "messageId": "m-1",
                "role": "user",
                "parts": [{"kind": "text", "text": "你好"}],
                "contextId": "ctx-1",
            }
        },
    }


class _StubRuntime:
    async def invoke(self, payload):
        from apps.orchestrator.public_runtime.result import (
            completed,
        )

        return completed(request_id=payload["request_id"], answer="你好。")


def _build(settings, monkeypatch=None):
    from apps.orchestrator.public_a2a.server import build_public_a2a_app

    return build_public_a2a_app(runtime=_StubRuntime(), settings=settings)


def test_bearer_auth_missing_wrong_right(monkeypatch):
    settings = PublicA2ASettings(
        listen_host="127.0.0.1",
        listen_port=8100,
        public_base_url="http://127.0.0.1:8100",
        auth_mode="bearer",
    )
    monkeypatch.setenv("HR_ASSISTANT_A2A_BEARER_TOKEN", "secret-token-xyz")
    client = TestClient(_build(settings))

    # card/health 无需bearer。
    assert client.get("/health").status_code == 200
    card = client.get("/.well-known/agent-card.json")
    assert card.status_code == 200
    assert card.json()["protocolVersion"] == "0.3.0"
    assert card.json()["url"] == "http://127.0.0.1:8100/"

    # JSON-RPC：缺失 → 401。
    assert client.post("/", json=_jsonrpc_body()).status_code == 401
    # 错误token → 401；响应体不含token。
    wrong = client.post(
        "/", json=_jsonrpc_body(), headers={"Authorization": "Bearer wrong"}
    )
    assert wrong.status_code == 401
    assert "secret-token-xyz" not in wrong.text
    # 正确token → 通过认证层（业务层正常处理）。
    right = client.post(
        "/", json=_jsonrpc_body(),
        headers={"Authorization": "Bearer secret-token-xyz"},
    )
    assert right.status_code == 200


def test_none_mode_no_auth_required():
    settings = PublicA2ASettings(
        listen_host="127.0.0.1",
        listen_port=8100,
        public_base_url="http://127.0.0.1:8100",
        auth_mode="none",
    )
    client = TestClient(_build(settings))
    response = client.post("/", json=_jsonrpc_body())
    assert response.status_code == 200


def test_health_reports_auth_mode():
    settings = PublicA2ASettings(
        listen_host="127.0.0.1",
        listen_port=8100,
        public_base_url="http://127.0.0.1:8100",
        auth_mode="bearer",
    )
    import os

    os.environ["HR_ASSISTANT_A2A_BEARER_TOKEN"] = "t"
    try:
        client = TestClient(_build(settings))
    finally:
        del os.environ["HR_ASSISTANT_A2A_BEARER_TOKEN"]
    body = client.get("/health").json()
    assert body["auth_mode"] == "bearer"
    assert body["protocol_version"] == "0.3.0"
    assert "token" not in str(body).lower()


def test_card_to_post_closed_loop():
    """真实HTTP闭环：起真实server，card.url必须POST回同一进程。"""
    import threading
    import time
    import urllib.request

    import uvicorn

    settings = PublicA2ASettings(
        listen_host="127.0.0.1",
        listen_port=0,
        public_base_url="",  # 由下面动态端口覆盖
        auth_mode="none",
    )
    # 选空闲端口：让uvicorn绑定后读回实际端口。
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    settings = PublicA2ASettings(
        listen_host="127.0.0.1",
        listen_port=port,
        public_base_url=f"http://127.0.0.1:{port}",
        auth_mode="none",
    )
    config = uvicorn.Config(
        _build(settings), host=settings.listen_host, port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.05)
    else:
        pytest.fail("server未就绪")

    try:
        card = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/.well-known/agent-card.json", timeout=5
        )
        import json

        card_url = json.load(card)["url"]
        assert card_url == f"http://127.0.0.1:{port}/"
        request = urllib.request.Request(
            card_url,
            data=json.dumps(_jsonrpc_body()).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response = urllib.request.urlopen(request, timeout=30)
        payload = json.load(response)
        # POST到card.url到达同一进程并返回合法JSON-RPC响应。
        assert payload["jsonrpc"] == "2.0"
        assert "result" in payload
    finally:
        server.should_exit = True
        thread.join(timeout=10)
