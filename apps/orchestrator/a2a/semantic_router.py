"""结构化语义路由：只做业务意图分类，不做执行。

目标是把"普通业务意图"从不断增长的 regex 中解放，改为受限枚举的结构化分类。
本组件只分类，不访问 Gaia / Knowledge / employee data / session secrets / 业务工具。

输出必须是严格枚举；绝不返回自由执行计划、URL、任意 Agent 名、工具名、employee id。

安全原则（WP-05 §9/§14）：
- low confidence → local（Local Root 一句追问澄清），绝不默认 Consult；
- 分类异常 → needs_clarification → local，绝不 silent remote dispatch。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    LEAVE_TRANSACTION = "leave_transaction"
    EMPLOYEE_SELF_DATA = "employee_self_data"
    HR_CONSULTATION = "hr_consultation"
    ATTENDANCE_CALCULATION = "attendance_calculation"
    GENERAL_LOCAL = "general_local"
    NEEDS_CLARIFICATION = "needs_clarification"


class RouteTarget(str, Enum):
    LOCAL = "local"
    CONSULT = "consult"
    EMPLOYEE_DATA = "employee_data"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# intent → target 固定映射（§7）：模型不得自由决定 target。
INTENT_TARGET: dict[Intent, RouteTarget] = {
    Intent.LEAVE_TRANSACTION: RouteTarget.LOCAL,
    Intent.EMPLOYEE_SELF_DATA: RouteTarget.EMPLOYEE_DATA,
    Intent.HR_CONSULTATION: RouteTarget.CONSULT,
    Intent.ATTENDANCE_CALCULATION: RouteTarget.CONSULT,
    Intent.GENERAL_LOCAL: RouteTarget.LOCAL,
    Intent.NEEDS_CLARIFICATION: RouteTarget.LOCAL,
}

_INTENT_VALUES = {item.value for item in Intent}
_TARGET_VALUES = {item.value for item in RouteTarget}
_CONFIDENCE_VALUES = {item.value for item in Confidence}


@dataclass(frozen=True)
class RouteDecision:
    intent: Intent
    target: RouteTarget
    confidence: Confidence
    reason_code: str | None = None


def safe_decision(intent: Intent, confidence: Confidence, reason_code: str = None) -> RouteDecision:
    """按固定 intent→target 映射构造决策；非白名单 intent 一律落 needs_clarification/local。"""
    if intent not in INTENT_TARGET:
        intent = Intent.NEEDS_CLARIFICATION
    return RouteDecision(
        intent=intent,
        target=INTENT_TARGET[intent],
        confidence=confidence,
        reason_code=reason_code,
    )


class SemanticRouter:
    """受限枚举语义分类器。

    classifier 是可注入的 `(text, session_state) -> dict`；生产环境使用结构化 LLM
    分类（root 模型配置），单测注入确定性替身。分类结果不合法或失败时安全兜底。
    未指定 classifier 时使用内置 default_classifier（有限意图集，非业务关键词堆砌）。
    """

    def __init__(self, classifier=None):
        self._classifier = classifier or default_classifier

    def classify(
        self, text: str, session_state: dict | None = None
    ) -> RouteDecision:
        if self._classifier is None:
            return safe_decision(
                Intent.NEEDS_CLARIFICATION, Confidence.LOW, "semantic_classifier_unavailable"
            )
        try:
            raw = self._classifier(text, session_state) if callable(self._classifier) else None
            if raw is None:
                return safe_decision(
                    Intent.NEEDS_CLARIFICATION, Confidence.LOW, "semantic_classifier_unavailable"
                )
            return self._parse(raw)
        except Exception:
            return safe_decision(
                Intent.NEEDS_CLARIFICATION, Confidence.LOW, "semantic_classify_failed"
            )

    @staticmethod
    def _parse(raw) -> RouteDecision:
        if not isinstance(raw, dict):
            return safe_decision(Intent.NEEDS_CLARIFICATION, Confidence.LOW, "invalid_raw")
        raw_intent = str(raw.get("intent", "")).strip()
        raw_conf = str(raw.get("confidence", "low")).strip().lower()
        if raw_intent not in _INTENT_VALUES:
            # 未知 intent：低置信度回归 local 澄清，不默认 Consult。
            return safe_decision(Intent.NEEDS_CLARIFICATION, Confidence.LOW, "unknown_intent")
        intent = Intent(raw_intent)
        conf = Confidence(raw_conf) if raw_conf in _CONFIDENCE_VALUES else Confidence.LOW
        # 忽略模型给的目标：target 由固定 intent→target 映射决定。
        return safe_decision(
            intent, conf, reason_code=str(raw.get("reason_code") or raw_intent)
        )


def build_semantic_router(*, classifier=None) -> SemanticRouter:
    return SemanticRouter(classifier=classifier)


# 内置默认分类器：有限的意图识别（每个意图列明确的语义信号），不是持续增长的业务
# 关键词正则。未命中 → needs_clarification（低置信度，由 guard 落 local）。
def default_classifier(text, session_state=None) -> dict:
    """有限意图集分类；未命中返回 needs_clarification。"""
    t = (text or "").strip()
    if _is_leave_intent(t):
        return {"intent": Intent.LEAVE_TRANSACTION.value, "confidence": "high",
                "reason_code": "leave_intent"}
    if _is_employee_data_intent(t):
        return {"intent": Intent.EMPLOYEE_SELF_DATA.value, "confidence": "high",
                "reason_code": "employee_data_intent"}
    if _is_attendance_intent(t):
        return {"intent": Intent.ATTENDANCE_CALCULATION.value, "confidence": "high",
                "reason_code": "attendance_intent"}
    if _is_consult_intent(t):
        return {"intent": Intent.HR_CONSULTATION.value, "confidence": "high",
                "reason_code": "consult_intent"}
    return {"intent": Intent.NEEDS_CLARIFICATION.value, "confidence": "low",
            "reason_code": "ambiguous"}


def _is_leave_intent(t: str) -> bool:
    if "请假" in t or "休年假" in t or "补登" in t:
        return True
    if re.search(r"(?:我要|我想|帮我|办|请|申请).{0,6}假", t):
        return True
    if re.search(r"(?:改到|改成|换成|时间).{0,4}(?:后天|明天|下|号)", t) or t.endswith("确认"):
        return True
    if re.search(r"明天想|后天|想调休|我要调休|请调休|想休", t) and "余额" not in t:
        return True
    return False


def _is_employee_data_intent(t: str) -> bool:
    # 本人或跨员工余额/医疗期/工龄/折算查询。
    if any(k in t for k in ("余额", "医疗期", "工龄", "参工", "折算", "还剩多少", "剩几天", "几天年假", "年假余额", "没休")):
        return True
    if re.search(r"(?:我|他|她|同事|别人|本|查下|查一下).{0,8}(?:年假|假期|病假|医疗期|工龄|折算|余额|调休)", t):
        return True
    return False


def _is_attendance_intent(t: str) -> bool:
    if any(k in t for k in ("迟到", "早退")) and any(k in t for k in ("扣", "分钟", "小时", "旷工", "怎么算", "多少", "算什么")):
        return True
    return False


def _is_consult_intent(t: str) -> bool:
    if any(k in t for k in ("制度", "政策", "规定", "怎么申请", "需要什么", "操作", "说明", "报销", "福利",
                            "需要证明", "证明吗", "怎么补", "多少天")):
        return True
    if re.search(r"(?:育儿假|年假|病假|婚假).{0,4}(?:几天|怎么|能|有|多少)", t):
        return True
    if "http" in t or "https" in t:
        return True
    return False
