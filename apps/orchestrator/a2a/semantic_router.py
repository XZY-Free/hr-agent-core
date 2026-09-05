"""结构化语义路由：只做业务意图分类，不做执行。

目标是把"普通业务意图"从不断增长的 regex 中解放，改为受限枚举的结构化分类。本组件只
分类，不访问 Gaia / Knowledge / employee data / session secrets / 业务工具。

生产分类由使用 root 模型配置（model_name + model_extra_config）的独立、无工具、以 root
chat 模式（``mode="chat"``）运行的 LLM Agent 完成，输出严格枚举；代码按固定 ``INTENT_TARGET``
映射生成 target，模型不得自由提供 target / URL / Agent 名 / 工具名 / employee id。
每次分类使用全新的随机 session_id，invocation-isolated，不积累分类历史。

安全原则（WP-05 §9/§14）：
- 未注入 classifier 的 ``SemanticRouter()`` 直接返回 needs_clarification / low，绝不内置
  分类（生产必须显式装配真实 LLM classifier，不允许 regex/keyword 双轨）；
- low confidence / 非法输出 / 分类异常 → local（Local Root 一句追问澄清），绝不默认
  Consult；
- 错误 reason_code 只能是稳定码（intent 值或安全码），不记录用户正文或模型输出。
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from veadk import Agent as VeadkAgent
from veadk import Runner as VeadkRunner


logger = logging.getLogger(__name__)


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

# 分类器的固定非业务 user_id（每次分类使用新的无身份随机 session_id，invocation-isolated）。
_CLASSIFIER_USER_ID = "semantic_classifier"


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


class ClassificationOutput(BaseModel):
    """模型结构化输出：intent 与 confidence 必填；extra forbid；模型不得给出 target/URL/Agent/工具/编号。"""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    confidence: Confidence


# --------------------------------------------------------------------------
# 生产 LLM 分类提示词：只分类，不执行；给出关键对照，避免"我想...假"被误判为办理。
# --------------------------------------------------------------------------
SEMANTIC_CLASSIFY_PROMPT = """你是企业人力智能助手的前置意图分类器。你只做一件事：把用户的一句话归类到下面严格枚举之一。你不回答、不执行、不生成任何业务内容，不调用任何工具。

输出要求：只输出一个 JSON 对象，禁止任何其他文字、代码块```、解释或前后缀。JSON 只有两个字段：
- "intent"：只能是下列枚举值之一；
- "confidence"：只能是 "high" / "medium" / "low"，必须显式给出。

枚举定义：
- "leave_transaction"：用户明确表达要办理、补登、修改请假单的动作（说"请假/休假"、想请/休/补登/改某假）；或给出"具体（非泛指、非疑问）的日期/时间/时长"连同某个假种，如"2026年10月21日上午半天年休假"，即使省略"请/休/办理"动词，也是明确的请假单办理动作。
- "employee_self_data"：用户明确查询本人（我/本人）的假期余额、全部/指定假种、医疗期、工龄、参工、年假折算。
- "hr_consultation"：用户咨询制度、政策、系统操作、薪酬福利、地区育儿假、HR 文档/所需材料（含"需要什么材料""怎么申请"）。
- "attendance_calculation"：用户明确要求计算迟到/早退的扣款金额或旷工天数，且给出可行时长。
- "general_local"：问候、闲聊、通用对话，无需任何业务处理。
- "needs_clarification"：只给出一个无法分辨"办理/余额/制度"的短语（如单独的假种名、考勤词、无具体日期/时长的泛称）。

confidence 语义（先定 intent，再据此给 confidence，必须严格照此）：
- "low" 只用于两类：① 只能给一个无法分辨"办理/余额/制度"的裸词（如单独的"年休假""调休"）；② 缺足以判定是哪一类互动的信息。
- 只要 intent 已被明确判定（leave_transaction / employee_self_data / hr_consultation / attendance_calculation 任一），confidence 就不得是 "low"，至少 "medium"；意图明确、无歧义时用 "high"。
- 请假单的"缺失字段"（假种未填、日期/时间/时长未填、事由未填）属于 LeaveDraft 后续收集，绝不因此把 intent 从 leave_transaction 降为 "low"——"我想请假"动作已明确，就是 "high"。

关键对照（务必照此判断）：
- "我想请假" → leave_transaction（high）
- "我想休年假" → leave_transaction（high）
- "2026年10月21日上午半天年休假" → leave_transaction（high）
- "我年假还有多少" → employee_self_data（high）
- "我2026年的年休假余额" → employee_self_data（high）
- "年假能跨年吗" → hr_consultation（high）
- "我想了解年假制度" → hr_consultation（high）
- "育儿假需要什么材料" → hr_consultation（high）
- "迟到17分钟扣多少" → attendance_calculation（high）
- "育儿假"（仅这两个字，无动作/无查询意图）→ needs_clarification（low）
- "年休假"（仅这两个字，无具体日期/时长）→ needs_clarification（low）

判断要点：
1. "余额/还有多少/剩几天/还剩"的本人查询与"怎么申请/需要什么材料/制度/政策/怎么算/能休几天"的制度流程咨询优先于下文"日期+假种"启发：先判 employee_self_data / hr_consultation。
2. 其余场景，只要用户给出"具体（非泛指、非疑问）的日期、时间或时长"并连同某个假种（如"2026年10月21日上午半天年休假"，或"下周三请一天假"），或明确"我想请/休/补登/改"某个假，就是 leave_transaction——即使省去"请/休/办理"动词。泛指或疑问的"几天""可以休几天""怎么申请"不构成具体时长。
3. 用户只写"年假""育儿假""调休""迟到"这类词，且无具体日期/时长、无动作、无查询对象 → needs_clarification。
4. "育儿假需要什么材料""怎么申请""制度""政策""能休几天"属申请流程/制度咨询 → hr_consultation，即使提及某假种。
5. "我2026年的年休假余额"虽含年份，但属于余额查询 → employee_self_data（不是 leave_transaction）。
6. 明确"我想请假/休假"或给出具体日期+假种的句子，即使假种/日期/时长/事由缺失，也是 leave_transaction（high）：缺失字段由 LeaveDraft 收集，不降为 low。

不要输出 "target" 或任何其它键。不要输出 URL、agent 名、工具名、员工编号。"""


# --------------------------------------------------------------------------
# 生产 LLM 分类器工厂：使用 root 的 model_name + model_extra_config。
# Agent 配置严格 `output_schema=ClassificationOutput`，返回文本只允许用 Pydantic
# `model_validate_json` 严格解析（无代码块/前后缀宽松解析）。
# 作为 VeadkRunner 根 Agent 必须以 ADK 支持的 ``mode="chat"`` 运行（root LLM Agent 不支持
# single_turn，否则 Runner.run 抛 ValueError）；每次分类使用新随机 session_id（uuid4）实现
# invocation-isolated，无全局锁、无固定会话累积，隔离不依赖 single_turn。
# 返回一个可 await 的 `(text, session_state) -> dict`；失败抛异常由 SemanticRouter 兜底。
# --------------------------------------------------------------------------
def build_llm_classifier(*, model_name: str, model_extra_config: dict):
    agent = VeadkAgent(
        name="semantic_classifier",
        model_name=model_name,
        model_extra_config=model_extra_config,
        instruction=SEMANTIC_CLASSIFY_PROMPT,
        tools=[],
        mode="chat",
        output_schema=ClassificationOutput,
    )
    runner = VeadkRunner(agent=agent, app_name="hr_classifier")

    async def classifier(text: str, session_state: dict | None = None) -> dict:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("分类器收到空文本")
        try:
            raw_text = await runner.run(
                text,
                user_id=_CLASSIFIER_USER_ID,
                session_id=f"cls-{uuid4().hex}",
            )
        except Exception as exc:
            logger.warning(
                "semantic_classifier_stage=model_invocation_failed error_type=%s",
                type(exc).__name__,
            )
            raise
        try:
            return ClassificationOutput.model_validate_json(raw_text).model_dump()
        except Exception as exc:
            logger.warning(
                "semantic_classifier_stage=output_validation_failed error_type=%s",
                type(exc).__name__,
            )
            raise

    return classifier


def build_semantic_router(*, classifier=None) -> "SemanticRouter":
    return SemanticRouter(classifier=classifier)


class SemanticRouter:
    """受限枚举语义分类器。

    classifier 是可注入的同步/异步 `(text, session_state) -> dict`，返回（或 await 后）
    一个含 intent/confidence 的对象。生产使用 `build_llm_classifier()`；单测可注入确定性
    替身。分类结果不合法、异常或未注入 classifier 时安全兜底到 needs_clarification/local。
    """

    def __init__(self, classifier=None):
        self._classifier = classifier

    async def classify(
        self, text: str, session_state: dict | None = None
    ) -> RouteDecision:
        if self._classifier is None:
            return safe_decision(
                Intent.NEEDS_CLARIFICATION, Confidence.LOW, "semantic_classifier_unavailable"
            )
        try:
            raw = self._classifier(text, session_state)
            if inspect.isawaitable(raw):
                raw = await raw
            return self._parse(raw)
        except Exception as exc:
            logger.warning(
                "semantic_classify_failed error_type=%s", type(exc).__name__
            )
            return safe_decision(
                Intent.NEEDS_CLARIFICATION, Confidence.LOW, "semantic_classify_failed"
            )

    @staticmethod
    def _parse(raw) -> RouteDecision:
        try:
            parsed = ClassificationOutput.model_validate(raw)
        except Exception:
            return safe_decision(Intent.NEEDS_CLARIFICATION, Confidence.LOW, "invalid_classification")
        # confidence 是模型给的；intent→target 由 INTENT_TARGET 固定映射（忽略模型给的 target）。
        return safe_decision(
            parsed.intent,
            parsed.confidence,
            reason_code=str(parsed.intent.value),
        )
