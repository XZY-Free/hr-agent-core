"""请假提交工具：校验链 + 干跑。

校验顺序（任一失败即返回对应 err）：
  no_permission → gender_mismatch → rest_day/not_scheduled
  → insufficient_balance → invalid_days
跨天修正：start_time > end_time 时 end_date +1。
末步经 calc_end_date 校正 end_date。

干跑：GAIA_DRY_RUN（默认 true）为 true 时只打日志、不调真实提交接口；
接口到位后在 _do_submit 补真实调用（一期 raise NotImplementedError，被 DRY_RUN 分支保护）。
"""
import os
from datetime import date, timedelta

from hr_agent.schemas.tool_result import ok, err
from hr_agent.schemas.leave_form import LeaveForm
from hr_agent.constants.leave_rules import LEAVE_GENDER_MAP
from hr_agent.constants.phrases import PHRASES
from hr_agent.tools.gaia.leave_query import get_leave_permissions, get_leave_balance
from hr_agent.tools.gaia.employee_query import get_employee_info
from hr_agent.tools.gaia.schedule_query import get_schedule
from hr_agent.tools.rules.leave_dates import calc_end_date


def _dry_run_enabled() -> bool:
    return os.getenv("GAIA_DRY_RUN", "true").lower() in ("true", "1", "yes")


def _do_submit(payload: dict, client) -> dict:
    """真实提交分支（一期未接入接口，禁止调用）。"""
    raise NotImplementedError("请假提交接口文档待业务方获取，一期走 DRY_RUN")


def submit_leave(type_name: str, start_date: str, end_date: str,
                 start_time: str, end_time: str, leave_days: float,
                 reasons: str, tool_context) -> dict:
    """请假单校验与提交（一期干跑）。"""
    # 1. 假期权限
    perms = get_leave_permissions(tool_context)
    if not perms["success"]:
        return perms
    allowed = {p["leave_type"] for p in perms["data"]}
    if type_name not in allowed:
        return err("no_permission", PHRASES["no_permission"])

    # 2. 性别限假
    if type_name in LEAVE_GENDER_MAP:
        info = get_employee_info(tool_context)
        if not info["success"]:
            return info
        sex = info["data"]["sex"]
        if LEAVE_GENDER_MAP[type_name] != sex:
            return err("gender_mismatch",
                       f"该假期仅限{'男性' if LEAVE_GENDER_MAP[type_name] == 'M' else '女性'}员工申请。")

    # 3. 首班排班：休息日 / 未排班
    sched_resp = get_schedule(start_date, start_date, tool_context)
    if not sched_resp["success"]:
        return sched_resp
    sched_first = sched_resp["data"]
    if not sched_first:
        return err("not_scheduled", PHRASES["not_scheduled"])
    if sched_first[0].get("start_time") == "00:00":
        return err("rest_day", PHRASES["rest_day"])

    # 4. 余额充足
    bal = get_leave_balance(type_name, tool_context)
    if not bal["success"]:
        return bal
    remain = bal["data"][0].get("remain", 0) if bal["data"] else 0
    if remain < leave_days:
        return err("insufficient_balance",
                   f"您的{type_name}余额为 {remain} 天，不足以申请 {leave_days} 天。")

    # 5. 天数合法
    if leave_days <= 0 or (leave_days * 2) % 1 != 0:
        return err("invalid_days", "请假天数必须是 0.5 的整数倍且大于 0。")

    # 末步：经 calc_end_date 校正 end_date（用完整范围排班），再叠加跨天修正
    full_sched_resp = get_schedule(start_date, end_date, tool_context)
    if not full_sched_resp["success"]:
        return full_sched_resp
    schedule = full_sched_resp["data"]
    corrected = calc_end_date(type_name, start_date, leave_days, schedule)
    ed = corrected["end_date"]
    # 跨天夜班：start_time > end_time 时 end_date +1（叠加在跳休推算结果之上）
    if start_time > end_time:
        d = date.fromisoformat(ed) + timedelta(days=1)
        ed = d.isoformat()

    form = LeaveForm(type_name=type_name, start_date=start_date, end_date=ed,
                     start_time=start_time, end_time=end_time,
                     leave_days=leave_days, reasons=reasons)
    payload = form.to_submit_payload()

    if _dry_run_enabled():
        print(f"[DRY_RUN] submit_leave payload: {payload}")
        return ok({"submitted": False, "dry_run": True, "form": payload})

    # 真实提交分支（一期不可达，DRY_RUN 默认开启）
    client = None  # 由 from_state(tool_context.state) 构造，待接口到位补
    return _do_submit(payload, client)
