# 02 — Track H1：HR A2A 端点与运行配置 Authority

## 1. 当前问题

当前 `card.py` 本地默认 `http://127.0.0.1:8000`，`server.py` uvicorn实际 `8100`。必须清除双Authority。

## 2. 唯一 Settings

新增：

```text
apps/orchestrator/public_a2a/settings.py
```

唯一负责：
```text
listen_host
listen_port
public_base_url
auth_mode
```

card/server/generator不得各自读取不同env。

## 3. env固定

```text
HR_ASSISTANT_A2A_HOST
HR_ASSISTANT_A2A_PORT
HR_ASSISTANT_A2A_PUBLIC_URL
HR_ASSISTANT_A2A_AUTH_MODE
```

本地默认：
```text
HOST=127.0.0.1
PORT=8100
PUBLIC_URL=http://127.0.0.1:8100
AUTH_MODE=none
```

显式PUBLIC_URL：
- 去尾slash；
- 只允许http/https；
- 禁query/fragment；
- Card.url = PUBLIC_URL + "/"

不能把0.0.0.0自动作为advertised URL。

## 4. server.py

`run_local_server()`只从Settings取host/port。

`build_public_a2a_app()`用同一Settings public_base_url构建Card。

删除硬编码8100。

## 5. card.py

删除LOCAL_BASE_URL和直接os.getenv。

默认依赖同一Settings。测试可显式注入settings，但不能有第二默认。

## 6. Card真实闭环测试

起真实本地HTTP server：
1. 选空闲端口；
2. settings public URL指向该端口；
3. GET well-known card；
4. 取card.url；
5. POST到card.url；
6. 必须到同一进程。

不能只做字符串测试。

## 7. Health

保留 `/health`，可返回：
```text
status
agent
version
protocol_version
auth_mode
```

禁止返回token、员工映射、内部子Agent状态明细。

## 8. import-time side effects

Settings不得在module import时不可逆冻结环境。builder/run入口创建settings；测试能显式注入。

## 9. Tests

必须覆盖默认8100、自定义port、自定义public URL、slash规范化、invalid scheme、0.0.0.0+explicit public URL、真实Card→POST闭环。

## 10. DoD

生产代码中不再存在8000/8100双默认，Settings成为唯一Endpoint Authority。
