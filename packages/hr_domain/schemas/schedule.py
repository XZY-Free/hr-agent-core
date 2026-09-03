"""排班三态模型与半天边界原始数据。

领域规则必须明确区分：
  WORK   —— 有明确排班记录且非休息班次
  REST   —— 有明确排班记录且是休息班次
  UNKNOWN—— 无排班记录 / 响应缺日期 / 排班为空 / 解析失败 / 查询范围外

UNKNOWN 不得当作 WORK 或 REST，也不得自动使用系统工作日。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from packages.hr_domain.constants.leave_rules import REST_SHIFT_PREFIXES


class DayStatus(str, Enum):
    WORK = "WORK"
    REST = "REST"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ScheduleFact:
    """单日排班事实，保留半天边界原始值（Gaia 返回有则保留，无则缺省）。"""

    shift_date: str            # yyyy-MM-dd
    shift_code: str
    shift_name: str = ""
    start_time: str = ""       # HH:mm
    end_time: str = ""
    meal_begin_time: str | None = None   # 半天边界 first-half 分界
    meal_end_time: str | None = None     # 半天边界 second-half 分界
    middle_time: str | None = None
    # 权威解析出的状态；由 ScheduleDayTable 根据 shift_code 计算，不在此处猜测。
    status: DayStatus = field(default=DayStatus.UNKNOWN, repr=False)

    @property
    def is_rest(self) -> bool:
        return any(self.shift_code.startswith(p) for p in REST_SHIFT_PREFIXES)

    @property
    def half_day_boundaries(self) -> tuple[str | None, str | None]:
        """返回 (first_half_end, second_half_start)。无半天边界时均为 None。"""
        return (
            self.meal_begin_time or self.middle_time,
            self.meal_end_time or self.middle_time,
        )


class ScheduleDayTable:
    """按日期索引的排班表；日期缺失→UNKNOWN，不再当成工作日。

    is_rest_known 语义：
      - 有记录：WORK / REST 明确；
      - 无记录：UNKNOWN（既非工作日也非休息日）。
    """

    def __init__(self, facts: list[ScheduleFact]):
        self.by_date: dict[str, ScheduleFact] = {
            f.shift_date: f for f in facts
        }

    def day(self, date_str: str) -> DayStatus:
        fact = self.by_date.get(date_str)
        if fact is None:
            return DayStatus.UNKNOWN
        return DayStatus.REST if fact.is_rest else DayStatus.WORK

    def fact(self, date_str: str) -> ScheduleFact | None:
        return self.by_date.get(date_str)

    def known_workdays(self) -> list[str]:
        """仅返回明确 WORK 的日期（升序）；UNKNOWN/REST 不计入。

        status 由 is_rest 动态判定；dataclass 的 status 字段仅作缓存/记录，
        不参与 WORK 判定，避免构造时遗漏造成未知被当工作日。
        """
        return sorted(d for d, f in self.by_date.items() if not f.is_rest)


def build_schedule_table(raw_items: list[dict]) -> ScheduleDayTable:
    """从 gaia 排班原始行构造三态排班表。

    原始行可能含 mealBeginTime/mealEndTime/middleTime 半天边界；无则保留 None，
    由规则层判断是否需要 schedule_detail_insufficient。
    """
    facts = []
    for item in raw_items or []:
        start = item.get("start_time")
        end = item.get("end_time")
        facts.append(ScheduleFact(
            shift_date=item.get("shift_date", ""),
            shift_code=item.get("shift_code", ""),
            shift_name=item.get("shift_name", ""),
            start_time=start or "",
            end_time=end or "",
            meal_begin_time=item.get("meal_begin_time"),
            meal_end_time=item.get("meal_end_time"),
            middle_time=item.get("middle_time"),
        ))
    return ScheduleDayTable(facts)
