"""仅拦截远程意图的AgentKit `/run_sse` ASGI中间件。"""

import json

from starlette.responses import Response


class DeterministicA2AMiddleware:
    def __init__(self, app, *, router):
        self.app = app
        self.router = router

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "POST" or scope.get("path") != "/run_sse":
            await self.app(scope, receive, send)
            return
        messages = []
        body = b""
        while True:
            message = await receive()
            messages.append(message)
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        try:
            payload = json.loads(body)
        except (TypeError, json.JSONDecodeError):
            await self._replay(scope, messages, receive, send)
            return
        routed = await self.router.route(payload)
        if routed is None:
            await self._replay(scope, messages, receive, send)
            return
        event = {
            "id": routed.request_id,
            "author": "root_agent",
            "content": {"role": "model", "parts": [{"text": routed.answer}]},
            "turnComplete": True,
            "a2a": {
                "target": routed.target,
                "status": routed.status,
                "request_id": routed.request_id,
                "error_code": routed.error_code,
            },
        }
        response = Response(
            content=f"data: {json.dumps(event, ensure_ascii=False)}\n\n",
            media_type="text/event-stream",
        )
        await response(scope, receive, send)

    async def _replay(self, scope, messages, receive, send):
        iterator = iter(messages)

        async def replay_receive():
            try:
                return next(iterator)
            except StopIteration:
                return await receive()

        await self.app(scope, replay_receive, send)
