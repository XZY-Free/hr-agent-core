"""Leave 草稿工具：模型用 typed 请求表达用户意图，领域服务推进状态机。

本文件是「领域服务 <-> ADK function_tool」的框架适配，不另建旁路业务 Authority。
模型只能写用户请求字段：type_name / requested_* / time_mode / requested_* /
duration_value / duration_unit / reason（LeaveDraftRequest，extra=forbid 拒绝未知键）。
不能写 draft_id / revision / status / authoritative 字段 / source / employee /
corp / secret——这些由领域服务与 request-bound HR context 决定。

草稿保存在真实已部署 ADK 会话状态（task-scoped session key 使同 context 不同 task
隔离）；只存用户意图/草稿/验证事实，不存 Gaia 凭据，也不从 session 读 employeeId。
身份与 Gaia 均走 require_employee_identity / require_gaia_provider。
"""

from __future__ import annotations

import re
from uuid import uuid4

from google.adk.tools.tool_context import ToolContext
from pydantic import ValidationError

from packages.hr_domain.execution.context import (
    current_hr_context,
    require_employee_identity,
    require_gaia_provider,
)
from packages.hr_domain.identity import IdentityResolutionError
from packages.hr_domain.schemas.leave_draft import (
    DraftStatus,
    LeaveDraftRequest,
    LeaveDraftState,
)
from packages.hr_domain.schemas.leave_form import LeaveForm
from packages.hr_domain.schemas.tool_result import err, ok
from packages.hr_domain.services.leave_draft_service import advance_leave_draft

STATE_KEY = "leave_draft"
DRAFT_TOOL_NAME = "save_leave_draft"
CONFIRM_TOOL_NAME = "confirm_leave_draft"

# 窄确认白名单：整句匹配（允许末尾标点/空白），拒绝任何"含确认字样"的句子，不用 substring。
# 目的是防止 "我没有确认 / 确认前我想改日期 / 请你确认信息" 之类被误判为授权。
_CONFIRM_PHRASES = frozenset({
    "确认", "确认提交", "确认申请", "可以提交",
    "按以上信息提交", "按以上提交", "确认无误请提交",
    "确认无误", "没问题", "就这样",
})
# 允许的句末标点与空白剥离集合。
_TERMINAL_PUNCT = "。！!．."


def _load_draft(tool_context: ToolContext) -> LeaveDraftState | None:
    raw = tool_context.state.get(STATE_KEY)
    if not isinstance(raw, dict):
        return None
    return LeaveDraftState.from_snapshot(raw)


def _save_draft(tool_context: ToolContext, draft: LeaveDraftState) -> None:
    tool_context.state[STATE_KEY] = draft.to_draft_snapshot()


def _new_draft() -> LeaveDraftState:
    return LeaveDraftState(draft_id=f"leave-{uuid4().hex}")


def _invocation_id(tool_context: ToolContext) -> str | None:
    value = getattr(tool_context, "invocation_id", None)
    return str(value) if value else None


def _user_text(tool_context: ToolContext) -> str:
    """本轮用户原文：来自 request-bound HR context 的原始请求消息，不猜、不剥离前缀。

    不再从拼接的"系统上下文 + 历史摘要 + 用户正文"里用 regex 反剥（历史摘要含空行会
    混入"确认"字眼）；未绑定 context（问候/制度咨询）则视为空。
    """
    ctx = current_hr_context()
    if ctx is None:
        return ""
    return (ctx.current_user_message or "").strip()


def _is_explicit_confirmation(user_text: str) -> bool:
    """窄确认：本轮整句恰好命中白名单的明确确认（允许末尾标点/空白）。

    不用 substring，也不用"含确认字眼的任意句"（"我没有确认 / 确认前我想改日期 /
    请你确认信息" 都不能授权）。摘要无论写什么都不进入本判定。
    """
    text = (user_text or "").strip()
    if not text:
        return False
    candidate = text
    while candidate and candidate[-1] in _TERMINAL_PUNCT:
        candidate = candidate[:-1]
    candidate = candidate.strip()
    return candidate in _CONFIRM_PHRASES


# ---------------- 确认态控制意图（continuation/control safety，不用 LLM 结果当 Authority） ----------------
# 用户在 READY 态下只是「否定确认 / 再看一下 / 查看当前申请」，并未提出请假数据修改。这类回合
# 模型只是表态或询问；若模型把 control 文本（如「我还没确认」）注入任一字段（尤其 reason），
# 领域 _apply_reason 因该串存在于用户原文而接受，导致 revision 被无意义递增。
# 因此这里在工具边界做小而确定的控制意图判定：命中纯控制意图时忽略模型全部保存参数，直接返回
# 现有草稿（id/revision/权威/reason/last_displayed 全不变，无 submission）。
#
# 判定采用「整句只表达控制意图」的规范化精确短语（full-match），而不是关键词 substring：
# 任何附加修改子句（如「查看当前申请，日期调整到后天」）都不会命中，进入原保存路径。不堆修改
# 关键词、不成为业务语义路由。摘要不进入本判定（调用方只传 current_user_message，不传历史摘要）。
_CONTROL_PHRASES = frozenset({
    # 否定确认 / 未确认
    "我还没确认", "我没有确认", "还没确认",
    # 再看 / 查看当前申请（只读）
    "确认之前我想再看一下", "确认之前我再看看",
    "给我看一下当前申请", "看一下当前申请", "查看当前申请", "看看当前申请",
    "看看申请", "查看申请",
})
# 规范化：只剥离句末标点、轻句末语气词与一个句首轻语气词，绝不剥离内容子句。
_TRAILING_PUNCT = frozenset("。！!．.~～……，,、")
_TRAILING_PARTICLES = frozenset({"吧", "呀", "啊", "哦", "呢", "嘛", "哈", "嗯", "啦", "咯", "吗"})
_LEADING_PARTICLES = frozenset({"嗯", "啊", "哦", "那个", "就是", "这个"})


def _normalize_control_text(user_text: str) -> str:
    text = (user_text or "").strip()
    if not text:
        return ""
    # 迭代剥离句末标点 / 轻语气词。
    while text:
        last = text[-1]
        if last in _TRAILING_PUNCT or last in _TRAILING_PARTICLES:
            text = text[:-1].strip()
            continue
        break
    # 只剥离一个句首轻语气词。
    for lead in sorted(_LEADING_PARTICLES, key=len, reverse=True):
        if text.startswith(lead):
            text = text[len(lead):].strip()
            break
    return text


def _is_control_intent(user_text: str) -> bool:
    """判定当前用户原文是否为「确认态控制意图」（否定确认 / 只看/查看，无任何附加修改子句）。

    规范化（剥离句末标点/轻语气词、句首轻语气词）后整句精确命中 _CONTROL_PHRASES 才算。
    只要还有附加修改子句，规范化结果就不会命中任何短语，返回 False 进入原保存路径。
    """
    normalized = _normalize_control_text(user_text)
    if not normalized:
        return False
    return normalized in _CONTROL_PHRASES


def _guard_control_intent(draft: LeaveDraftState | None, user_text: str) -> dict | None:
    """确认态纯控制意图拦截：返回现成草稿 payload；非纯控制意图返回 None 走原流程。

    复用 `_payload` / `ok` 生成快照与确认文案，不复制 payload；不 _save_draft、不改
    last_displayed，使草稿对象与 session state 原样返回。
    """
    if draft is None or draft.status is not DraftStatus.READY_FOR_CONFIRMATION:
        return None
    if not _is_control_intent(user_text):
        return None
    return ok(_payload("ready_for_confirmation", draft, [], None))


def _identity_or_gaia():
    """解析身份 + provider；失败返回 (None, None, err)。"""
    try:
        employee_id = require_employee_identity().employee_id
        provider = require_gaia_provider()
    except IdentityResolutionError:
        return None, None, err("identity_unverified", "当前身份无法完成本人数据查询。")
    except Exception:
        return None, None, err("gaia_error", "当前无法办理请假，请联系管理员检查服务配置。")
    return provider, employee_id, None


def _validation_error(result) -> dict | None:
    if result.error_code:
        return {"code": result.error_code, "message": result.error_message}
    return None


def _missing_fields_list(missing) -> list[str]:
    if missing is None:
        return []
    names: list[str] = []
    if missing.type_name:
        names.append("type_name")
    if missing.date:
        names.append("date")
    if missing.time_or_duration:
        names.append("time_or_duration")
    if missing.reason:
        names.append("reason")
    return names


_LABELS = {
    "type_name": "假期类型",
    "date": "日期",
    "time_or_duration": "时间/时长",
    "reason": "事由",
}


def _summary(payload: dict) -> str:
    """由结构化草稿/缺失/错误确定性生成文案，不用 LLM 文本改写权威数字。"""
    if payload.get("validation_error"):
        return payload["validation_error"].get("message") or "暂时无法办理。"
    missing = payload.get("missing_fields") or []
    if missing:
        return "请补充：" + "、".join(_LABELS[m] for m in missing) + "。"
    draft = payload.get("draft") or {}
    status = payload.get("status")
    if status == "ready_for_confirmation":
        # 只取草稿权威值渲染，不用 LLM 改写；日期/时段/时长/类型/非空事由都来自草稿快照，
        # 保证用户看到的确认摘要与权威草稿逐字段一致。
        unit = draft.get("authoritative_duration_unit")
        unit_label = "小时" if unit == "hour" else "天"
        value = draft.get("authoritative_duration_value")
        type_name = draft.get("normalized_type_name") or ""
        start = draft.get("authoritative_start_date")
        start_time = draft.get("authoritative_start_time")
        end = draft.get("authoritative_end_date")
        end_time = draft.get("authoritative_end_time")
        reason = (draft.get("reason") or "").strip()
        text = (
            f"请核对您的{type_name}申请：{start} {start_time} 至 {end} {end_time}，"
            f"共 {value} {unit_label}。"
        )
        if reason:
            text += f"事由：{reason}。"
        text += "确认无误后请确认提交。"
        return text
    if status in ("confirmed", "terminal"):
        return "已确认您的请假申请。"
    return "请补充请假信息，以便完成申请。"


def _payload(status: str, draft: LeaveDraftState | None,
             missing_fields: list[str], validation: dict | None,
             *, extra: dict | None = None) -> dict:
    payload = {
        "status": status,
        "draft": draft.to_draft_snapshot() if draft is not None else None,
        "missing_fields": missing_fields,
        "validation_error": validation,
    }
    payload["answer"] = _summary(payload)
    if extra:
        payload.update(extra)
    return payload


def _reject(draft: LeaveDraftState | None, code: str, message: str,
            tool_context: ToolContext, *, status: str | None = None) -> dict:
    """拒绝（原子校验失败 / confirm 拒绝）也携带当前草稿安全状态，防止被口头"成功"吞掉。"""
    if draft is not None:
        st = status or (draft.status.value if hasattr(draft.status, "value") else draft.status)
        return ok(_payload(st, draft, _missing_fields_list(None),
                           {"code": code, "message": message}))
    return ok(_payload(status or "collecting", None, [], {"code": code, "message": message}))


# ---------------- 模型内 schema 纠错（前 2 次让模型自纠正，超限给用户安全错误） ----------------
_SCHEMA_RETRY_KEY = STATE_KEY + "._schema_retry"
_SCHEMA_RETRY_LIMIT = 2


def _field_errors(exc) -> list[dict]:
    """只带安全元数据的字段纠错：field 路径 / 错误类型 / 合法枚举（expected），不含 input_value。

    用于 save 工具对 schema 校验失败时的模型内纠错回报，避免模型填自然语言单位/时段后被
    立刻投影成缺 Draft 的公共终态。
    """
    field_errors: list[dict] = []
    for e in exc.errors():
        loc = e.get("loc")
        path = ".".join(str(x) for x in loc if x is not None) or "request"
        entry: dict = {"field": path, "type": e.get("type") or "value_error"}
        ctx = e.get("ctx") or {}
        expected = ctx.get("expected")
        if isinstance(expected, str):
            entry["expected"] = expected
        elif isinstance(expected, (list, tuple, set)):
            try:
                entry["expected"] = sorted(str(x) for x in expected)
            except Exception:
                entry["expected"] = "~"
        if "given" in ctx:
            # 只给类型类别，不暴露用户原值/原始响应。
            entry["given_type"] = type(ctx["given"]).__name__
        field_errors.append(entry)
    return field_errors


def _schema_retry_state(tool_context: ToolContext) -> dict:
    raw = tool_context.state.get(_SCHEMA_RETRY_KEY)
    if isinstance(raw, dict) and isinstance(raw.get("count"), int):
        return raw
    return {"turn": None, "count": 0}


def _schema_retry_save(tool_context: ToolContext, state: dict) -> None:
    tool_context.state[_SCHEMA_RETRY_KEY] = state


def _schema_retry_clear(tool_context: ToolContext) -> None:
    tool_context.state[_SCHEMA_RETRY_KEY] = None


def _schema_retry(tool_context: ToolContext, exc) -> dict:
    """schema 校验失败：让模型在本轮内修正（前 2 次），不立刻给用户缺 Draft 结果。

    - 以当前真实 invocation_id 作为 turn key（不用用户原文做身份）：同一 invocation 内前两次
      schema 失败返回 retryable_for_model，第三次安全显式失败；新 invocation 即便原文完全相同
      也从 0 重置计数。
    - 不修改现有草稿 / 不 revision / 不 last_displayed。
    - invocation_id 缺失则 fail closed（不以用户原文冒充身份），直接给用户明确安全失败，绝不
      无限重试 / 吞异常 / 伪造草稿成功。
    """
    invocation_id = _invocation_id(tool_context)
    if not invocation_id:
        # 无真实回合边界：不能把用户原文当身份（否则相邻相同原文会串计数），也不进入无限
        # 模型纠错循环。直接走明确安全失败，用户可见、有界。
        return _reject(_load_draft(tool_context), "invalid_request",
                       "请假请求暂时无法识别，请更换表达方式后再试。", tool_context)
    state = _schema_retry_state(tool_context)
    if state.get("turn") != invocation_id:
        state = {"turn": invocation_id, "count": 0}
    count = state.get("count", 0)
    if count < _SCHEMA_RETRY_LIMIT:
        state["count"] = count + 1
        state["turn"] = invocation_id
        _schema_retry_save(tool_context, state)
        return {
            "success": False,
            "error_type": "invalid_request",
            "retryable_for_model": True,
            "field_errors": _field_errors(exc) if exc is not None else
                [{"field": "request", "type": "value_error"}],
        }
    # 超过上限：明确失败并给用户安全错误（保留当前草稿状态，便于换表达后再试）。
    return _reject(_load_draft(tool_context), "invalid_request",
                   "请假请求暂时无法识别，请更换表达方式后再试。", tool_context)


# --------------------------------------------------------------------------
# 可信原文显式零时长归一化：显式 0 是用户数据，覆盖模型可能省略/改写的零值。
# 只认「零」量词：阿拉伯 0 / 0.0 / 00 与中文 零，允许可选「个」；绝不匹配 10 里的 0
# （(?<!\d)）或 0.5 的整数部（(?!\.?\d)）。不用于非零 / 缺省 / 显式 null。
# --------------------------------------------------------------------------
_ZERO_NUM = r"(?:零|(?<!\d)(?:0\.0|00|0)(?!\.?\d))"
_ZERO_HOUR_UNIT = _ZERO_NUM + r"\s*个?\s*(?:小时|钟头)"
_ZERO_DAY_UNIT = _ZERO_NUM + r"\s*个?\s*天"
_ZERO_HOUR_RE = re.compile(_ZERO_HOUR_UNIT)
_ZERO_DAY_RE = re.compile(_ZERO_DAY_UNIT)
# 显式「HH:MM 前」结束边界且其后紧跟零小时量词（如「17:00前0小时」）：
# 只认排班字面时间，绝不从任意文本另造一个班次边界。
_ZERO_HOUR_BOUNDARY_RE = re.compile(
    r"(?P<end>(?:[01]\d|2[0-3]):[0-5]\d)\s*(?:之前|以前|前)\s*" + _ZERO_HOUR_UNIT
)


def _normalize_explicit_zero_quantity(
    request: LeaveDraftRequest, user_text: str
) -> LeaveDraftRequest:
    """可信当前用户原文里的显式零时长是用户数据，覆盖模型可能省略/改写的零值。

    只在原文明确出现零小时/零天时写入零，并用原文「HH:MM 前」字面边界保住显式结束
    时间锚（如「17:00前0小时」）以阻止领域收集；非零 / 缺省 / 显式 null 一律原样返回。
    零小时与零天同时出现则不动（单位冲突交给领域/模型路径，不在此强选）。
    不做 truthiness（x or default）、不改原模型、不打印/记录用户文本。
    """
    if not user_text:
        return request
    hour_match = _ZERO_HOUR_RE.search(user_text)
    day_match = _ZERO_DAY_RE.search(user_text)
    if not (hour_match or day_match):
        return request
    if hour_match and day_match:
        # 零小时与零天同时出现：不强行选单位，保留已校验的模型请求，交给领域判定。
        return request
    if hour_match:
        override: dict = {
            "requested_hours": 0.0,
            "duration_value": 0.0,
            "duration_unit": "hour",
            "time_mode": "explicit_hours",
        }
        boundary = _ZERO_HOUR_BOUNDARY_RE.search(user_text)
        if boundary is not None:
            override["requested_end_time"] = boundary.group("end")
    else:  # day_match
        override = {"duration_value": 0.0, "duration_unit": "day"}
    # 用 exclude_unset 保留其余已显式提供的字段（含显式 None），再叠加可信零值覆盖；
    # 重新校验使 model_fields_set 记为「已提供」，领域据此按用户数据保留 0，绝不改成 1。
    data = request.model_dump(exclude_unset=True)
    data.update(override)
    return LeaveDraftRequest.model_validate(data)


def save_leave_draft(request: LeaveDraftRequest, tool_context: ToolContext) -> dict:
    """表达用户请假请求并推进权威草稿。

    Args:
        request: LeaveDraftRequest 结构化输入；模型只能写用户请求字段。ADK 会用 Pydantic
            转型，但转换失败会保留原 dict，此处再校验：schema 校验失败走模型内纠错（前 2 次
            retryable_for_model），不修改草稿也不 revision；解析成功才清计数并进入业务流转。

    顺序：先判定「确认态纯控制意图」（否定确认 / 再看 / 查看当前申请）——这属于 control safety，
    位于 request schema 校验与身份/Gaia 之前。命中则忽略模型保存参数直接返回现有 ready 草稿，
    不创建新 draft、不因模型传错 schema 或 Gaia 暂时失败而改判；非控制意图才做 schema 校验、
    身份/Gaia 与领域推进。
    """
    # 控制意图先判：从可信当前请求取 user_text、加载现有 draft（不新建），命中即返回。
    user_text = _user_text(tool_context)
    draft = _load_draft(tool_context)
    guarded = _guard_control_intent(draft, user_text)
    if guarded is not None:
        return guarded

    if isinstance(request, dict):
        try:
            request = LeaveDraftRequest.model_validate(request)
        except ValidationError as exc:
            # schema 校验失败：让模型本轮内纠错，不立刻投影成缺 Draft 的公共结果。
            return _schema_retry(tool_context, exc)
        except Exception:
            # 非 schema 类解析异常：也不伪造草稿，交给模型重试。
            return _schema_retry(tool_context, None)
    if not isinstance(request, LeaveDraftRequest):
        return _schema_retry(tool_context, None)

    # 解析成功：清掉 schema 纠错计数，进入业务流转。
    _schema_retry_clear(tool_context)

    # 可信当前用户原文中的显式零时长是用户数据：在身份/Gaia 与领域处理前做确定性归一化，
    # 覆盖模型可能省略/改写的零值（含「17:00前0小时」的显式结束边界），非零/缺省原样。
    request = _normalize_explicit_zero_quantity(request, user_text)

    provider, employee_id, err_resp = _identity_or_gaia()
    if err_resp is not None:
        return err_resp

    draft = _load_draft(tool_context) or _new_draft()
    result = advance_leave_draft(
        draft, request, provider=provider, employee_id=employee_id, user_text=user_text,
    )
    if result.status is DraftStatus.READY_FOR_CONFIRMATION:
        draft.last_displayed_invocation_id = _invocation_id(tool_context)
    _save_draft(tool_context, draft)
    missing_fields = _missing_fields_list(result.missing)
    status = result.status.value if hasattr(result.status, "value") else result.status
    return ok(_payload(status, draft, missing_fields, _validation_error(result)))


def confirm_leave_draft(revision: int, tool_context: ToolContext) -> dict:
    """确认最新草稿（只接 draft revision）。

    仅允许：当前草稿 ready_for_confirmation、revision 等于当前草稿 revision、
    上一轮确有展示（last_displayed_invocation_id 有效且非本轮）、本轮为窄确认。
    模型参数 revision 不作为用户授权证据；授权来自本轮原始用户文本的明确确认。
    成功写入 terminal 且保存，调用原有干跑/提交边界；失败携带当前草稿安全状态。
    """
    provider, employee_id, err_resp = _identity_or_gaia()
    if err_resp is not None:
        return err_resp

    draft = _load_draft(tool_context)
    user_text = _user_text(tool_context)
    if draft is None:
        return _reject(None, "draft_missing", "当前没有待确认的请假草稿。", tool_context)

    if draft.status is not DraftStatus.READY_FOR_CONFIRMATION:
        return _reject(draft, "not_ready_for_confirmation",
                       "请假草稿尚未通过校验，暂时无法确认。", tool_context,
                       status=draft.status.value)

    # revision 必须是 int；type(revision) is int 排除 bool（True 是 int 子类）。
    if type(revision) is not int or revision != draft.revision:
        return _reject(draft, "stale_revision", "请假草稿已更新，请重新核对后确认。",
                       tool_context)

    prev_display = draft.last_displayed_invocation_id
    cur = _invocation_id(tool_context)
    # 前一轮展示与本轮 invocation 都必须非空且不同，才代表"新的一轮"确认。
    if not prev_display or not cur or prev_display == cur:
        return _reject(draft, "confirm_requires_next_turn",
                       "请在新的一轮确认最新请假信息。", tool_context)

    if not _is_explicit_confirmation(user_text):
        return _reject(draft, "confirm_requires_confirmation",
                       "请明确确认后再提交。", tool_context)

    # 到达确认：先构造内部 LeaveForm；若权威字段不完整则拒绝（保持草稿）。
    try:
        form = LeaveForm.from_authoritative(draft)
    except ValueError:
        return _reject(draft, "authority_incomplete",
                       "请假草稿权威字段不完整，暂时无法提交，请重新核对。", tool_context)

    # 延迟导入避免模块级循环；走原干跑/提交边界（默认 GAIA_DRY_RUN=true）。
    from apps.orchestrator.local_leave.submit import finalize_leave_submission

    try:
        submission = finalize_leave_submission(form, provider, employee_id)
    except Exception:
        # 异常只输出安全固定话术；保留原草稿的 ready/权威/前一轮展示信息，可重试。
        return _reject(draft, "submit_failed", "请假提交暂时失败，请稍后重试或联系管理员。",
                       tool_context, status=draft.status.value)

    # 既有边界成功：dry_run 且返回 form dict，或直连提交 submitted=True。两者都算成功，
    # 绝不把裸 submitted:false 当成功，也不把 unsupported_hour / 提交失败记成功。
    submitted_ok = submission.get("submitted") is True
    dry_run_ok = submission.get("dry_run") is True and isinstance(submission.get("form"), dict)
    if submitted_ok or dry_run_ok:
        # 成功才写 TERMINAL 并保存；返回 status=terminal 与草稿快照一致。
        draft.status = DraftStatus.TERMINAL
        _save_draft(tool_context, draft)
        return ok(_payload("terminal", draft, [], None,
                           extra={"confirm_revision": draft.revision, "submission": submission}))

    # 失败（unsupported_hour / submit_failed 等）：不把失败记成功、不抹掉重试所需状态；
    # 保留原草稿 ready/权威/前一轮展示信息，返回稳定错误，后续明确确认仍可重试。
    # error_type 兼容 submit 返回 `error_type` 或 `unsupported_hour: True` 两种形态。
    err_code = submission.get("error_type") or (
        "unsupported_hour" if submission.get("unsupported_hour") is True else "submit_failed"
    )
    return _reject(draft, err_code,
                   submission.get("message") or "请假提交暂时失败，请稍后重试或联系管理员。",
                   tool_context, status=draft.status.value)
