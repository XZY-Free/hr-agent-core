"""显式 Leave Draft 状态模型。

不是 FastGPT 全局变量，不是聊天文本里的状态；是一个带 provenance 的单一业务
草稿对象。关键交易事实必须能追溯来源（user / normalized_user / schedule /
rule / system），模型生成且无法追溯来源的值不允许进入权威表单。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class DraftStatus(str, Enum):
    COLLECTING = "collecting"
    READY_FOR_VALIDATION = "ready_for_validation"
    VALIDATION_FAILED = "validation_failed"
    READY_FOR_CONFIRMATION = "ready_for_confirmation"
    CONFIRMED = "confirmed"
    TERMINAL = "terminal"


class FieldSource(str, Enum):
    USER = "user"
    NORMALIZED_USER = "normalized_user"
    SCHEDULE = "schedule"
    RULE = "rule"
    SYSTEM = "system"


class TimeMode(str, Enum):
    FULL_DAY = "full_day"
    FIRST_HALF = "first_half"
    SECOND_HALF = "second_half"
    EXPLICIT_RANGE = "explicit_range"
    EXPLICIT_HOURS = "explicit_hours"


class DurationUnit(str, Enum):
    DAY = "day"
    HOUR = "hour"


class HourAnchor(str, Enum):
    """显式小时语义锚点：只表达“相对班次起点/终点”的意义，不携带具体时间。

    模型只能填枚举（shift_start / shift_end），绝不能把实际排班时间填进 here；
    具体起止时间由领域按排班事实计算并标注来源（schedule/rule）。
    """

    SHIFT_START = "shift_start"
    SHIFT_END = "shift_end"


@dataclass(frozen=True)
class Provenanced:
    """带来源的值。来源不可追溯时不应进入权威表单。"""

    value: object
    source: FieldSource


@dataclass
class LeaveDraftState:
    """单一业务草稿的可变状态；由 LeaveDraftService 创建与演进。"""

    draft_id: str
    revision: int = 0
    status: DraftStatus = DraftStatus.COLLECTING

    # 假期类型
    raw_type_expression: str | None = None
    normalized_type_name: str | None = None
    type_code: str | None = None
    type_source: FieldSource | None = None

    # 日期（用户请求层）
    requested_date_expression: str | None = None
    requested_date_segments: list[str] = field(default_factory=list)
    requested_start_date: str | None = None
    requested_end_date: str | None = None
    # 权威日期层
    authoritative_start_date: str | None = None
    authoritative_end_date: str | None = None

    # 时间表达
    time_mode: TimeMode | None = None
    requested_start_time: str | None = None
    requested_end_time: str | None = None
    requested_hours: float | None = None
    hour_anchor: HourAnchor | None = None
    authoritative_start_time: str | None = None
    authoritative_end_time: str | None = None

    # 时长（unit 分离）
    duration_value: float | None = None
    duration_unit: DurationUnit | None = None
    authoritative_duration_value: float | None = None
    authoritative_duration_unit: DurationUnit | None = None
    # 权威字段来源（供后续生产工具消费，避免来自模型/不可追溯值的权威表单）
    authoritative_start_date_source: FieldSource | None = None
    authoritative_end_date_source: FieldSource | None = None
    authoritative_duration_value_source: FieldSource | None = None
    authoritative_duration_unit_source: FieldSource | None = None
    authoritative_start_time_source: FieldSource | None = None
    authoritative_end_time_source: FieldSource | None = None

    # 理由
    reason: str | None = None
    reason_source: FieldSource | None = None

    # 校验结果与失效标记
    invalidation_reason: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    # 最近一次校验失败的结构化类别（用于 read-only / reason-only 保持错误，不升级）。
    status_error_code: str | None = None
    status_error_message: str = ""

    # 面向确认：该 revision 在多少个"用户回合"被展示（用于拒绝同一 invocation 内
    # draft+confirm 的"直接提交"伪确认）。存 invocation_id 仅作轮次判别，不是权威。
    last_displayed_invocation_id: str | None = None

    def to_draft_snapshot(self) -> dict:
        """输出公共 data.draft 字段快照（copy，不返回内部引用）。

        只含现有 schema 字段名，不做别名/容器兼容；用户请求层与权威层分开。
        """
        def _enum(value):
            return value.value if hasattr(value, "value") else value

        return {
            "draft_id": self.draft_id,
            "revision": self.revision,
            "status": _enum(self.status),
            "normalized_type_name": self.normalized_type_name,
            "type_code": self.type_code,
            "type_source": _enum(self.type_source),
            "raw_type_expression": self.raw_type_expression,
            "requested_date_expression": self.requested_date_expression,
            "requested_start_date": self.requested_start_date,
            "requested_end_date": self.requested_end_date,
            "requested_date_segments": list(self.requested_date_segments),
            "requested_start_time": self.requested_start_time,
            "requested_end_time": self.requested_end_time,
            "time_mode": _enum(self.time_mode),
            "requested_hours": self.requested_hours,
            "hour_anchor": _enum(self.hour_anchor),
            "duration_value": self.duration_value,
            "duration_unit": _enum(self.duration_unit),
            "authoritative_start_date": self.authoritative_start_date,
            "authoritative_end_date": self.authoritative_end_date,
            "authoritative_start_time": self.authoritative_start_time,
            "authoritative_end_time": self.authoritative_end_time,
            "authoritative_duration_value": self.authoritative_duration_value,
            "authoritative_duration_unit": _enum(self.authoritative_duration_unit),
            "authoritative_start_date_source": _enum(self.authoritative_start_date_source),
            "authoritative_end_date_source": _enum(self.authoritative_end_date_source),
            "authoritative_start_time_source": _enum(self.authoritative_start_time_source),
            "authoritative_end_time_source": _enum(self.authoritative_end_time_source),
            "authoritative_duration_value_source": _enum(self.authoritative_duration_value_source),
            "authoritative_duration_unit_source": _enum(self.authoritative_duration_unit_source),
            "reason": self.reason,
            "reason_source": _enum(self.reason_source),
            "invalidation_reason": self.invalidation_reason,
            "validation_errors": list(self.validation_errors),
            "status_error_code": self.status_error_code,
            "status_error_message": self.status_error_message,
            "last_displayed_invocation_id": self.last_displayed_invocation_id,
        }

    @classmethod
    def from_snapshot(cls, raw: dict) -> "LeaveDraftState":
        """从 to_draft_snapshot 的 JSON-safe 快照恢复草稿（session 状态存取用）。"""

        def _enum(cls_, value):
            try:
                return cls_(value) if value else None
            except (ValueError, TypeError):
                return None

        draft = cls(draft_id=raw.get("draft_id") or "", revision=int(raw.get("revision") or 0))
        draft.status = _enum(DraftStatus, raw.get("status")) or DraftStatus.COLLECTING
        draft.normalized_type_name = raw.get("normalized_type_name")
        draft.type_code = raw.get("type_code")
        draft.type_source = _enum(FieldSource, raw.get("type_source"))
        draft.raw_type_expression = raw.get("raw_type_expression")
        draft.requested_date_expression = raw.get("requested_date_expression")
        draft.requested_start_date = raw.get("requested_start_date")
        draft.requested_end_date = raw.get("requested_end_date")
        draft.requested_date_segments = list(raw.get("requested_date_segments") or [])
        draft.requested_start_time = raw.get("requested_start_time")
        draft.requested_end_time = raw.get("requested_end_time")
        draft.requested_hours = raw.get("requested_hours")
        draft.hour_anchor = _enum(HourAnchor, raw.get("hour_anchor"))
        draft.time_mode = _enum(TimeMode, raw.get("time_mode"))
        draft.duration_value = raw.get("duration_value")
        draft.duration_unit = _enum(DurationUnit, raw.get("duration_unit"))
        draft.authoritative_start_date = raw.get("authoritative_start_date")
        draft.authoritative_end_date = raw.get("authoritative_end_date")
        draft.authoritative_start_time = raw.get("authoritative_start_time")
        draft.authoritative_end_time = raw.get("authoritative_end_time")
        draft.authoritative_duration_value = raw.get("authoritative_duration_value")
        draft.authoritative_duration_unit = _enum(DurationUnit, raw.get("authoritative_duration_unit"))
        draft.authoritative_start_date_source = _enum(FieldSource, raw.get("authoritative_start_date_source"))
        draft.authoritative_end_date_source = _enum(FieldSource, raw.get("authoritative_end_date_source"))
        draft.authoritative_start_time_source = _enum(FieldSource, raw.get("authoritative_start_time_source"))
        draft.authoritative_end_time_source = _enum(FieldSource, raw.get("authoritative_end_time_source"))
        draft.authoritative_duration_value_source = _enum(FieldSource, raw.get("authoritative_duration_value_source"))
        draft.authoritative_duration_unit_source = _enum(FieldSource, raw.get("authoritative_duration_unit_source"))
        draft.reason = raw.get("reason")
        draft.reason_source = _enum(FieldSource, raw.get("reason_source"))
        draft.invalidation_reason = raw.get("invalidation_reason")
        draft.validation_errors = list(raw.get("validation_errors") or [])
        draft.status_error_code = raw.get("status_error_code")
        draft.status_error_message = raw.get("status_error_message") or ""
        draft.last_displayed_invocation_id = raw.get("last_displayed_invocation_id")
        return draft


@dataclass(frozen=True)
class MissingFields:
    """由草稿结构化判定缺失的槽位；input_required 的唯一状态来源。"""

    type_name: bool = False
    date: bool = False
    time_or_duration: bool = False
    reason: bool = False

    def field_names(self) -> list[str]:
        names = []
        if self.type_name:
            names.append("假期类型")
        if self.date:
            names.append("日期")
        if self.time_or_duration:
            names.append("时间/时长")
        if self.reason:
            names.append("事由")
        return names

    def is_empty(self) -> bool:
        return not (self.type_name or self.date or self.time_or_duration or self.reason)


class LeaveDraftRequest(BaseModel):
    """模型对用户请假请求的typed表达输入。

    extra=forbid：模型不能写 draft_id / revision / status / authoritative 字段 /
    source / employee / corp / secret 等——未知键一律拒绝，不部分更新。
    零值（duration_value=0）保留给领域判 invalid_duration，绝不 x or 1；
    omitted 字段保持草稿旧值；explicit null 表示清空该字段并失效依赖；
    reason="" 表示清空（empty reason 表示清空理由）。
    """
    model_config = ConfigDict(extra="forbid")

    type_name: str | None = None
    requested_start_date: str | None = None
    requested_end_date: str | None = None
    requested_date_segments: list[str] | None = None
    # 枚举类型：JSON schema 生成明确 enum，模型必须填合法值（全天→full_day、半天、明确
    # 起止/小时），不能再填自然语言。非法值在入口触发 ValidationError → save 工具返回
    # retryable_for_model 纠错，让模型在本轮修正，不会立刻投影成缺 Draft 的公共结果。
    time_mode: TimeMode | None = None
    requested_start_time: str | None = None
    requested_end_time: str | None = None
    requested_hours: float | None = None
    duration_unit: DurationUnit | None = None
    hour_anchor: HourAnchor | None = None
    duration_value: float | None = None
    reason: str | None = None

    # --- 严格校验：enum/date/time/finite/type（bool 不能当数）。任何非法输入在进入
    # 领域前由 Pydantic 原子拒绝（ValidationError → 工具返回 invalid_request），
    # 绝不部分更新。零值（0）仍是合法 finite，交领域判 invalid_duration。
    @field_validator("type_name", mode="before")
    @classmethod
    def _type_name(cls, v):
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("type_name 必须是字符串")
        return v

    @field_validator("requested_start_date", "requested_end_date", mode="before")
    @classmethod
    def _date(cls, v):
        if v is None:
            return None
        if not isinstance(v, str) or not _DATE_RE.match(v):
            raise ValueError("日期必须是 yyyy-MM-dd")
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(f"非法日期：{v}") from None
        return v

    @field_validator("requested_date_segments", mode="before")
    @classmethod
    def _segments(cls, v):
        if v is None:
            return None
        if not isinstance(v, list) or not all(
            isinstance(x, str) and _DATE_RE.match(x) for x in v
        ):
            raise ValueError("requested_date_segments 必须是合法日期字符串列表")
        for item in v:
            try:
                date.fromisoformat(item)
            except ValueError:
                raise ValueError(f"非法日期：{item}") from None
        return v

    @field_validator("requested_start_time", "requested_end_time", mode="before")
    @classmethod
    def _time(cls, v):
        if v is None:
            return None
        if not isinstance(v, str) or not _TIME_RE.match(v):
            raise ValueError("时间必须是 HH:MM")
        return v

    @field_validator("requested_hours", "duration_value", mode="before")
    @classmethod
    def _finite_num(cls, v):
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("数字字段必须是有限数值，布尔值不受支持")
        value = float(v)
        if not math.isfinite(value):
            raise ValueError("数字字段必须有限")
        return value
