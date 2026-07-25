"""盖亚 OpenAPI 客户端：JWT 缓存、统一请求封装。地址与环境按《接口适配清单.md》原样。"""
import time
import requests

BASE_URLS = {"prod": "https://openapi.gaiaworkforce.com",
             "sandbox": "https://openapi-s.gaiaworkforce.com"}
JWT_TTL_SECONDS = 25 * 60   # 无法解析 exp 时的保守缓存时长
TIMEOUT = 30                # 与旧工作流一致


class GaiaClient:
    def __init__(self, corp_id: str, client_secret: str, grant_type: str):
        self.corp_id = corp_id
        self.client_secret = client_secret
        self.grant_type = grant_type
        self._jwt_cache: dict[str, tuple[str, float]] = {}   # env -> (jwt, expire_ts)

    def get_jwt(self, env: str) -> str:
        cached = self._jwt_cache.get(env)
        if cached and cached[1] > time.time():
            return cached[0]
        resp = requests.post(
            f"{BASE_URLS[env]}/identity/api/v1/oauth",
            data={"grant_type": self.grant_type, "corp_id": self.corp_id,
                  "client_secret": self.client_secret},
            timeout=TIMEOUT)
        body = resp.json()
        if not (body.get("result") and body.get("code") == 200):
            raise RuntimeError(f"获取盖亚JWT失败: {body.get('message')}")
        jwt = body["data"]
        self._jwt_cache[env] = (jwt, time.time() + JWT_TTL_SECONDS)
        return jwt

    def request(self, env: str, method: str, path: str, *, json_body=None,
                params=None, extra_headers=None, tenant: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.get_jwt(env)}"}
        if tenant:
            headers["tenant"] = tenant
        if extra_headers:
            headers.update(extra_headers)
        resp = requests.request(method, f"{BASE_URLS[env]}{path}",
                                json=json_body, params=params,
                                headers=headers, timeout=TIMEOUT)
        return resp.json()


def from_state(state) -> GaiaClient:
    """从 ADK session state 构造客户端（业务变量由调用方注入 state）。"""
    return GaiaClient(corp_id=state["corp_id"],
                      client_secret=state["client_secret"],
                      grant_type=state["grant_type"])
