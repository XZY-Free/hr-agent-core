"""显式 Leave Draft 状态模型。

不是 FastGPT 全局变量，不是聊天文本里的状态；是一个带 provenance 的单一业务
草稿对象。关键交易事实必须能追溯来源（user / normalized_user / schedule /
rule / system），模型生成且无法追溯来源的值不允许进入权威表单。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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
    authoritative_start_time: str | None = None
    authoritative_end_time: str | None = None

    # 时长（unit 分离）
    duration_value: float | None = None
    duration_unit: DurationUnit | None = None
    authoritative_duration_value: float | None = None
    authoritative_duration_unit: DurationUnit | None = None

    # 理由
    reason: str | None = None
    reason_source: FieldSource | None = None

    # 校验结果与失效标记
    invalidation_reason: str | None = None
    validation_errors: list[str] = field(default_factory=list)


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
