"""路由决策：确定性 guard + 结构化语义路由，不再用大量业务关键词 regex。

职责分层（WP-05）：
- DeterministicGuard：continuation owner 优先、协议/安全约束、本轮保留的精确控制命令
  （page / handoff / cancel / greeting——原样保持，不改业务行为）。
- Structured Semantic Router：普通业务意图分类（intent/target/confidence 严格枚举），
  不再由 `_LEAVE_ACTION`/`_EMPLOYEE_DATA` 等业务 regex 决定。
- 低置信度 → local（Root 追问澄清），绝不默认 Consult。
"""

import re
from dataclasses import dataclass
from enum import Enum

from apps.orchestrator.a2a.semantic_router import (
    Confidence,
    Intent,
    RouteDecision,
    SemanticRouter,
)


class RouteTarget(str, Enum):
    LOCAL = "local"
    CONSULT = "consult"
    EMPLOYEE_DATA = "employee_data"


@dataclass(frozen=True)
class RouteSelection:
    """路由裁决：target 之外保留 semantic decision 的 intent/confidence/reason。

    通过值返回（不可变），不共享任何可变 last-decision 状态；供 router 判断是否走
    local clarification / Root / 远程派发。
    ``clarification_required`` 标记低置信度/歧义语义：此时 target 仍为 LOCAL（固定
    local/consult/employee_data 三值契约），需要直接产出固定本地澄清而非进入 Root。
    """

    target: RouteTarget
    decision: RouteDecision | None = None
    clarification_required: bool = False


# 本轮不改业务行为的精确控制命令（§3）。保留原语义，仅作为 guard 精确命中。
_CANCEL = re.compile(r"取消|撤回|销假")
_PAGE = re.compile(r"^(?:打开|进入|跳转|查看).{0,20}(?:明细|排班|申请|信息|记录|统计|表单|余额)")
_HANDOFF = re.compile(r"转人工|找客服|投诉")
_GREETING = re.compile(r"^(?:你好|您好|嗨|hi|hello|谢谢|再见)[！!。.？?]*$", re.IGNORECASE)


class DeterministicRouteTable:
    """确定性 guard + continuation 归属 + 语义路由器兜底。"""

    def __init__(self, semantic_router: SemanticRouter | None = None):
        self._semantic_router = semantic_router or SemanticRouter()
        # continuation owner：(user_id, session_id) -> RouteTarget
        self._remote_pending: dict[tuple[str, str], RouteTarget] = {}

    async def decide(
        self,
        text: str,
        user_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> RouteSelection:
        """路由决策主入口（async：会 await 结构化语义分类器）。

        continuation owner 以 (user_id, session_id, task_id) 为键：不同 task 不继承
        另一个暂停任务的 owner（§10.3），补充消息只回到自己的 task。
        decide 无 task_id 时退化为 session 级 owner（兼容测试契约）。
        owner / 精确控制 guard 保持同步且优先级不变；只有第 3 步语义分类被 await。
        """
        message = text.strip()

        # 1. continuation owner 优先：原任务的补充消息必须回到原 owner，不做语义重分类。
        if user_id is not None and session_id is not None:
            owner = self._lookup_owner(user_id, session_id, task_id)
            if owner is not None:
                return RouteSelection(target=owner)

        # 2. 协议/安全约束（本轮保留的精确控制命令）→ 仍进入 Root。
        if _CANCEL.search(message) or _PAGE.search(message) or _HANDOFF.search(message):
            return RouteSelection(target=RouteTarget.LOCAL)
        if _GREETING.fullmatch(message):
            return RouteSelection(target=RouteTarget.LOCAL)

        # 3. 普通业务意图 → 结构化语义路由器（await，不阻塞 event loop）。
        decision = await self._semantic_router.classify(
            message, self._session_state(user_id, session_id)
        )
        # 保留 semantic decision 的 intent/confidence/reason，供 router 决定澄清/Root/远程。
        return RouteSelection(
            target=self._target(decision, message),
            decision=decision,
            clarification_required=self._clarification_required(decision),
        )

    @staticmethod
    def _clarification_required(decision: RouteDecision) -> bool:
        # 低置信度或歧义 → 固定本地澄清（绝不默认 Consult / 进入 Root/Leave）。
        return decision.confidence is Confidence.LOW or decision.intent is Intent.NEEDS_CLARIFICATION

    @staticmethod
    def _target(decision: RouteDecision, _message: str) -> RouteTarget:
        # 低置信度/歧义时 target 仍是 LOCAL（三值契约），由 clarification_required 标记；否则按映射。
        if decision.confidence is Confidence.LOW or decision.intent is Intent.NEEDS_CLARIFICATION:
            return RouteTarget.LOCAL
        return RouteTarget(decision.target.value)

    @staticmethod
    def _session_state(user_id, session_id) -> dict | None:
        if user_id is None and session_id is None:
            return None
        return {"user_id": user_id, "session_id": session_id}

    def _owner_key(self, user_id: str, session_id: str, task_id: str | None):
        if task_id is not None:
            return (user_id, session_id, task_id)
        return (user_id, session_id)

    def _lookup_owner(self, user_id: str, session_id: str, task_id: str | None):
        if task_id is not None:
            return self._remote_pending.get((user_id, session_id, task_id))
        # 无 task_id：先找 task 级，再回退 session 级。
        return self._remote_pending.get((user_id, session_id))

    def record_remote_status(
        self,
        *,
        user_id: str,
        session_id: str,
        target: RouteTarget,
        status: str,
        task_id: str | None = None,
    ) -> None:
        """记录远程续接归属：need_more_information 时绑定 owner，终态清除。

        补充消息回到原 owner，不重新用自然语言分类；key 含 task_id 以隔离不同 task。
        """
        key = self._owner_key(user_id, session_id, task_id)
        if status == "need_more_information":
            self._remote_pending[key] = target
        else:
            self._remote_pending.pop(key, None)
