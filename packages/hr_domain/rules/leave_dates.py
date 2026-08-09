"""27 类假期跳休推算（规则核心）。

数据源与算法：旧工作流 §3.7 原文。禁止"优化"舍入与命名。
- days 不可解析或 > 27 → shrink_workday：start 向后找第一个工作日、end 取排班最后一个工作日
- days ≤ 27 且类型标记连续（或不在表内）→ continuous：end = start + (ceil(days)-1)
- 类型标记跳休 → skip_rest：从 start 起按排班跳过休息日，数满 ceil(days) 个工作日；
  start 不在排班范围内 → 回退自然日累加（mode 仍为 skip_rest）
"""
import math
from datetime import date, timedelta

from packages.hr_domain.constants.leave_rules import SKIP_RESTDAY_MAP, REST_SHIFT_PREFIXES


def _is_rest(shift_code: str | None) -> bool:
    if not shift_code:
        return False
    return any(shift_code.startswith(p) for p in REST_SHIFT_PREFIXES)


def _parse_date(s: str) -> date:
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def calc_end_date(type_name: str, start_date: str, days: float, schedule: list[dict]) -> dict:
    """根据假期类型与排班推算请假结束日期与模式。

    Args:
        type_name: 假期类型名（如 "年休假"）
        start_date: 起始日期 yyyy-MM-dd
        days: 请假天数（0.5 的整数倍）
        schedule: 排班列表，项结构同 get_schedule 的 data（含 shift_date/shift_code）

    Returns:
        {"start_date", "end_date", "mode"}，mode ∈ {"continuous","skip_rest","shrink_workday"}
    """
    # 解析 days
    try:
        days_n = float(days)
        if math.isnan(days_n):
            days_n = None
    except (TypeError, ValueError):
        days_n = None

    # 构造排班查找表：date -> is_rest
    sched_map: dict[date, bool] = {}
    for item in schedule:
        d = _parse_date(item["shift_date"])
        sched_map[d] = _is_rest(item.get("shift_code"))

    start = _parse_date(start_date)

    # shrink 模式：days 不可解析或 > 27
    if days_n is None or days_n > 27:
        sd = start
        for _ in range(366):
            if sd in sched_map and not sched_map[sd]:
                break
            sd = sd + timedelta(days=1)
        else:
            sd = start  # 找不到工作日，回退
        workdays = sorted(d for d, rest in sched_map.items() if not rest)
        ed = workdays[-1] if workdays else start
        return {"start_date": sd.isoformat(), "end_date": ed.isoformat(),
                "mode": "shrink_workday"}

    n = math.ceil(days_n)  # 占用工作日数（半天向上取整）

    # 类型模式：不在表默认连续（True）
    is_continuous = SKIP_RESTDAY_MAP.get(type_name, True)

    if is_continuous:
        end = start + timedelta(days=n - 1)
        return {"start_date": start_date, "end_date": end.isoformat(),
                "mode": "continuous"}

    # 跳休模式
    if start not in sched_map:
        # start 不在排班内 → 回退自然日累加
        end = start + timedelta(days=n - 1)
        return {"start_date": start_date, "end_date": end.isoformat(),
                "mode": "skip_rest"}

    # 从 start 起按排班跳过休息日，数满 n 个工作日
    count = 0
    cur = start
    end = start
    max_iter = len(sched_map) + n + 10
    for _ in range(max_iter):
        is_rest_day = sched_map.get(cur)  # None=排班外
        if is_rest_day is not True:  # 工作日 or 排班外（排班外按工作日计）
            count += 1
            end = cur
            if count >= n:
                break
        cur = cur + timedelta(days=1)
    return {"start_date": start_date, "end_date": end.isoformat(),
            "mode": "skip_rest"}
