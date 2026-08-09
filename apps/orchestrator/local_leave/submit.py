"""请假提交工具：校验链 + 干跑。

校验顺序（任一失败即返回对应 err）：
  no_permission → gender_mismatch → rest_day/not_scheduled
  → insufficient_balance → invalid_days
跨天修正：start_time > end_time 时 end_date +1。
末步经 calc_end_date 校正 end_date。

GAIA_DRY_RUN（默认 true）为 true 时不调提交接口，直接返回请假单 JSON——
这是**业务确认的正式形态**，不是临时凑合：2026-07-25 业务确认调用链为
「后端 → 智能体」，智能体只输出请假单 JSON，由后端自行调盖亚提交接口
（见 迁移梳理/接口适配清单.md §8、迁移梳理报告 §9.3）。
GAIA_DRY_RUN=false 走 _do_submit 直连提交，是为"将来若改由智能体自行提交"
预留的示例实现，字段映射待接口文档核对，默认不启用。
"""
import os
from datetime import date, timedelta

from packages.hr_domain.schemas.tool_result import ok, err
from packages.hr_domain.schemas.leave_form import LeaveForm
from packages.hr_domain.constants.leave_rules import LEAVE_GENDER_MAP
from packages.hr_domain.constants.phrases import PHRASES
from packages.hr_domain.gaia.client import from_state
from packages.hr_domain.gaia.leave_query import get_leave_permissions, get_leave_balance
from packages.hr_domain.gaia.employee_query import get_employee_info
from packages.hr_domain.gaia.schedule_query import get_schedule
from packages.hr_domain.rules.leave_dates import calc_end_date

# 提交接口路径/环境：接口文档到位后核对。路径按盖亚同类接口（如
# getEmployeeCanApplyLeaveType）的形态占位，{corp_id} 运行时替换。
SUBMIT_PATH = os.getenv(
    "GAIA_SUBMIT_PATH",
    "/atd-webapi/api/gaiaStandard/leave/submitLeaveApply/{corp_id}",
)
SUBMIT_ENV = os.getenv("GAIA_SUBMIT_ENV", "sandbox")


def _dry_run_enabled() -> bool:
    return os.getenv("GAIA_DRY_RUN", "true").lower() in ("true", "1", "yes")


def _do_submit(payload: dict, client, state) -> dict:
    """直连提交盖亚请假接口——**示例实现，字段映射待接口文档核对**。

    正式链路不走这里（智能体只输出 JSON，由后端提交，见模块文档）。本函数
    是"将来若改为智能体直连"的对接骨架：请求/响应结构按盖亚同类接口的惯例
    （result/code/message 三段式 + tenant 头）写就，拿到接口文档后需要核对：
      1. SUBMIT_PATH 与 SUBMIT_ENV（生产还是沙箱）
      2. payload 字段名——当前沿用 LeaveForm.to_submit_payload() 的旧系统
         leave_support 结构，另补 employeeId；真实接口可能要求不同的键名
      3. 成功判定字段——当前按 result=True 且 code=200
    """
    body = dict(payload, employeeId=state["employeeId"])
    try:
        resp = client.request(
            SUBMIT_ENV, "POST",
            SUBMIT_PATH.format(corp_id=state["corp_id"]),
            json_body=body, tenant=state["corp_id"])
    except Exception as e:
        return err("gaia_error", f"提交请假单失败：{e}")

    if not (resp.get("result") and resp.get("code") == 200):
        return err("submit_failed", f"提交请假单失败：{resp.get('message') or '接口未返回成功'}")
    return ok({"submitted": True, "dry_run": False, "form": body,
               "apply_id": (resp.get("data") or {}).get("applyId")
               if isinstance(resp.get("data"), dict) else None})


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
        # 正式形态：不提交，把请假单 JSON 交回给后端（业务确认的调用链）
        print(f"[DRY_RUN] submit_leave payload: {payload}")
        return ok({"submitted": False, "dry_run": True, "form": payload})

    # 直连提交（示例实现，默认不启用）
    return _do_submit(payload, from_state(tool_context.state), tool_context.state)
