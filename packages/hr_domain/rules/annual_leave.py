"""年假工龄折算。算法照旧代码节点逐行移植，禁止"优化"舍入方式。

档位规则：<10 年 5 天、≥10 年 10 天。
跨档年（满 10 年的纪念日落在当年）按参工纪念日分段：之前按 5 天档折算、之后按 10 天档折算。
"""
import math
from datetime import date

from packages.hr_domain.schemas.tool_result import ok, err
from packages.hr_domain.gaia.employee_query import get_employee_info
from packages.hr_domain.gaia.leave_query import get_leave_balance


def split_year_quota(month: int, day: int, year: int) -> dict:
    """按参工纪念日（year 年的 month-day）把当年折成两段年假配额。

    旧代码节点算法原样移植：
      leave_before = floor(days_before/total_days*5*10)/10
      leave_after  = floor(days_after /total_days*10*10)/10
    days_before 含当日；闰年 total_days=366。
    """
    total_days = 366 if _is_leap(year) else 365
    anniversary = date(year, month, day)
    jan1 = date(year, 1, 1)
    days_before = (anniversary - jan1).days + 1   # 含当日
    days_after = total_days - days_before
    leave_before = math.floor(days_before / total_days * 5 * 10) / 10
    leave_after = math.floor(days_after / total_days * 10 * 10) / 10
    return {"before": leave_before, "after": leave_after}


def _is_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def calc_annual_leave(tool_context) -> dict:
    """根据员工工龄折算年假天数并附年假余额。

    - 工龄 <10 年（非跨档年）→ flat 5
    - 工龄 ≥10 年（非跨档年）→ flat 10
    - 当年为工龄满 10 年的跨档年 → split（纪念日之前 5 天档、之后 10 天档）
    """
    info = get_employee_info(tool_context)
    if not info["success"]:
        return info  # 透传错误

    d = info["data"]
    years = int(d["social_service_year"])
    hire_month = int(d["hire_month"])
    hire_day = int(d["hire_day"])

    today = date.today()
    anniversary_this_year = date(today.year, hire_month, hire_day)
    if today >= anniversary_this_year:
        # 今年纪念日已过 → 参工年份 = today.year - years
        can_start_year = today.year - years
    else:
        # 今年纪念日未过 → 参工年份 = today.year - years - 1
        can_start_year = today.year - years - 1
    ten_year_year = can_start_year + 10   # 满 10 年的年份

    # 附年假余额查询结果
    balance = get_leave_balance("年休假", tool_context)
    balance_data = balance.get("data") if balance.get("success") else None

    if today.year == ten_year_year:
        quota = split_year_quota(hire_month, hire_day, today.year)
        return ok({
            "mode": "split",
            "before": quota["before"],
            "after": quota["after"],
            "anniversary": f"{hire_month:02d}-{hire_day:02d}",
            "balance": balance_data,
        })
    if years < 10:
        return ok({"mode": "flat", "quota": 5, "balance": balance_data})
    return ok({"mode": "flat", "quota": 10, "balance": balance_data})
