"""考勤量化计算输入/输出模型。

模型只负责从自然语言提取结构（kind + duration_minutes）；单位换算、边界、豁免、
扣款、旷工全部由确定性领域规则完成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AttendanceKind(str, Enum):
    LATE = "late"
    EARLY_LEAVE = "early_leave"


@dataclass(frozen=True)
class AttendanceRecord:
    kind: AttendanceKind
    duration_minutes: int
    source_expression: str = ""
    sequence: int = 0


@dataclass(frozen=True)
class MonthlyExemptContext:
    """月度小额迟到/早退免扣上下文（迟与早退分别维护，不擅自合并）。

    每个池的已用免扣次数：int 表示已知次数（含 0），None 表示未提供/未知，
    二者必须区分，不能把「未知」当作 0。负数或非法值在构造期 fail closed
    （抛出 ValueError），绝不转成 0。
    """

    late_prior_exempt: int | None = None
    early_leave_prior_exempt: int | None = None

    def __post_init__(self) -> None:
        for name in ("late_prior_exempt", "early_leave_prior_exempt"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("月度免扣次数必须是非负整数或未知(None)")


@dataclass
class AttendanceItemResult:
    sequence: int
    kind: AttendanceKind
    original_minutes: int
    chargeable_bucket: int | None        # 10 分钟档桶；严重记录为 None
    deduction: float
    absence_days: float
    exemption_applied: bool
    is_severe: bool
    needed_context: bool = False          # 10 分钟内但缺月度豁免上下文
    error_code: str | None = None
    error_message: str = ""


@dataclass
class AttendanceResult:
    records: list[AttendanceItemResult] = field(default_factory=list)
    total_deduction: float = 0.0
    total_absence_days: float = 0.0
    unresolved_context: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str = ""


@dataclass(frozen=True)
class AttendanceInput:
    records: list[AttendanceRecord]
    exempt_context: MonthlyExemptContext | None = None
