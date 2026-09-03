"""请假提交工具：领域规则校验链 + 干跑。

校验顺序（WP-02 §15）：type normalization → permission → gender →
date/continuity → schedule evidence → time/duration → balance → confirmation。

模型传入的 leave_days / start_time / end_time 只是用户意图，不是最终事实；
权威日期与时长由领域规则基于排班计算（连续/跳休、半天边界、夜班跨日）。
余额比较使用权威 duration 且 hour/day 单位不混算。

GAIA_DRY_RUN（默认 true）为 true 时不调提交接口，直接返回请假单 JSON——业务确认
的正式形态（智能体只输出请假单 JSON，由后端自行调盖亚提交接口）。
GAIA_DRY_RUN=false 走 _do_submit 直连提交，为示例实现，默认不启用。

本工具不处理最终业务动作 JSON 的假实现问题——那属于本工程包明确排除范围。
"""
import os
from datetime import date, timedelta

from packages.hr_domain.schemas.tool_result import ok, err
from packages.hr_domain.schemas.leave_form import LeaveForm
from packages.hr_domain.constants.leave_rules import LEAVE_GENDER_MAP, normalize_type_name
from packages.hr_domain.gaia.client import from_state
from packages.hr_domain.gaia.provider import GaiaProvider
from packages.hr_domain.rules.leave_dates import compute_leave_dates
from packages.hr_domain.rules.leave_duration import (
    DurationUnit,
    authoritative_duration,
)
from packages.hr_domain.schemas.leave_draft import TimeMode
from packages.hr_domain.schemas.schedule import build_schedule_table
from packages.hr_domain.execution.context import (
    require_employee_identity,
    require_gaia_provider,
)
from packages.hr_domain.identity import IdentityResolutionError

# 提交接口路径/环境：接口文档到位后核对。
SUBMIT_PATH = os.getenv(
    "GAIA_SUBMIT_PATH",
    "/atd-webapi/api/gaiaStandard/leave/submitLeaveApply/{corp_id}",
)
SUBMIT_ENV = os.getenv("GAIA_SUBMIT_ENV", "sandbox")


def _dry_run_enabled() -> bool:
    return os.getenv("GAIA_DRY_RUN", "true").lower() in ("true", "1", "yes")


def _do_submit(payload: dict, client, state) -> dict:
    """直连提交盖亚请假接口——示例实现，字段映射待接口文档核对。"""
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


def _gaia_or_identity_error():
    """从 request-bound HR context 解析 provider + employee。

    返回 (provider, employee_id) 或 err 结构。
    """
    try:
        employee_id = require_employee_identity().employee_id
        provider = require_gaia_provider()
    except IdentityResolutionError:
        return None, None, err("identity_unverified", "当前身份无法完成本人数据查询。")
    except Exception:
        return None, None, err("gaia_error", "当前无法办理请假，请联系管理员检查服务配置。")
    return provider, employee_id, None


def submit_leave(type_name: str, start_date: str, end_date: str,
                 start_time: str, end_time: str, leave_days: float,
                 reasons: str, tool_context) -> dict:
    """请假单校验与提交（一期干跑）。"""
    provider, employee_id, err_resp = _gaia_or_identity_error()
    if err_resp is not None:
        return err_resp
    provider: GaiaProvider

    # 0. type normalization（年假 → 年休假）
    normalized = normalize_type_name(type_name)
    if normalized is None:
        return err("unknown_type", f"未知假期类型：{type_name}。")
    type_name = normalized

    # 1. permission
    perms = provider.leave_permissions(employee_id)
    if not perms["success"]:
        return perms
    allowed = {p["leave_type"] for p in perms["data"]}
    if type_name not in allowed:
        return err("no_permission", "您暂无权限申请该类型假期，请核对后重试或咨询 HR。")

    # 2. gender
    if type_name in LEAVE_GENDER_MAP:
        info = provider.employee_info(employee_id)
        if not info["success"]:
            return info
        sex = info["data"]["sex"]
        if LEAVE_GENDER_MAP[type_name] != sex:
            label = "男性" if LEAVE_GENDER_MAP[type_name] == "M" else "女性"
            return err("gender_mismatch", f"该假期仅限{label}员工申请。")

    # 3. schedule evidence（首个请求日起，用于三态排班）
    sched_resp = provider.schedule(start_date, end_date or start_date, employee_id)
    if not sched_resp["success"]:
        return sched_resp
    table = build_schedule_table(sched_resp["data"])

    # 4. 权威日期（连续 / 跳休 真实分开；UNKNOWN 不当工作日；无 27 天分支）
    workdays = max(1, round(leave_days)) if leave_days > 0 else 1
    dates = compute_leave_dates(
        type_name=type_name,
        requested_start_date=start_date,
        requested_end_date=end_date or start_date,
        calendar_duration=leave_days if leave_days > 0 else 1.0,
        workdays_requested=workdays,
        table=table,
    )
    if dates.error_code:
        if dates.error_code == "rest_day":
            return err("rest_day", "该日期是正常休息日，不需要请假。")
        if dates.error_code == "schedule_unknown":
            return err("not_scheduled", "您选择的日期排班尚未明确，暂无法办理。")
        return err(dates.error_code, dates.error_message or "排班范围不足，暂无法办理。")
    ed = dates.end_date

    # 5. 权威时长（半天边界、hour/day 不混）
    time_mode = _infer_time_mode(leave_days, start_time, end_time)
    sched_fact = table.fact(dates.start_date)
    duration = authoritative_duration(
        time_mode=time_mode,
        schedule_fact=sched_fact,
        requested_start_time=start_time,
        requested_end_time=end_time,
        requested_hours=leave_days if time_mode is TimeMode.EXPLICIT_HOURS else None,
    )
    if duration.error_code:
        return err(duration.error_code, duration.error_message)
    auth_duration = duration.duration_value
    auth_unit = duration.duration_unit
    auth_start_time = duration.start_time
    auth_end_time = duration.end_time

    # 跨天夜班：仅在取得权威班次时段后，start>end 时 end_date +1。
    if auth_start_time and auth_end_time and auth_start_time > auth_end_time:
        ed = (date.fromisoformat(ed) + timedelta(days=1)).isoformat()

    # 6. balance（使用权威 duration，unit 匹配）
    bal = provider.leave_balance(type_name, employee_id)
    if not bal["success"]:
        return bal
    remain = _balance_remain(bal["data"], auth_unit)
    if remain is None:
        return err("balance_unknown", "假期余额暂时无法确认。")
    if remain < (auth_duration or 0):
        unit_label = "小时" if auth_unit is DurationUnit.HOUR else "天"
        return err("insufficient_balance",
                   f"您的{type_name}余额为 {remain} {unit_label}，不足以申请 {auth_duration} {unit_label}。")

    form = LeaveForm(type_name=type_name, start_date=start_date, end_date=ed,
                     start_time=auth_start_time or start_time,
                     end_time=auth_end_time or end_time,
                     leave_days=auth_duration if auth_unit is DurationUnit.DAY
                     else leave_days,
                     reasons=reasons or "")
    payload = form.to_submit_payload()

    if _dry_run_enabled():
        print(f"[DRY_RUN] submit_leave payload: {payload}")
        return ok({"submitted": False, "dry_run": True, "form": payload})

    # 直连提交（示例实现，默认不启用）
    return _do_submit(payload, from_state(_legacy_state(employee_id, provider)),
                      {"employeeId": employee_id, "corp_id": provider.config.corp_id})


def _infer_time_mode(leave_days: float, start_time: str | None, end_time: str | None) -> TimeMode:
    """从工具入参推断时间表达。

    模型传入的 start/end/leave_days 是意图；time_mode 只用于选择权威计算分支，
    权威时段/时长本身由领域规则基于排班得出。hour/day 不混算。

    优先级：明确天数（0.5 / ≥1）→ 按全天/半天；否则再看显式时间对 / 小时数。
    """
    if leave_days and (leave_days * 2) % 1 != 0:
        return TimeMode.EXPLICIT_HOURS
    if leave_days and leave_days >= 1.0:
        return TimeMode.FULL_DAY
    if leave_days == 0.5:
        return TimeMode.FIRST_HALF
    if start_time and end_time and start_time != end_time:
        return TimeMode.EXPLICIT_RANGE
    return TimeMode.FIRST_HALF


def _balance_remain(balance: list[dict], unit: DurationUnit | None) -> float | None:
    row = next((it for it in (balance or []) if it.get("leave_name")), None)
    if row is None or row.get("remain") is None:
        return None
    return float(row["remain"])


def _legacy_state(employee_id: str, provider: GaiaProvider) -> dict:
    """仅用于 _do_submit 示例（默认不启用）的兼容 state 构造。"""
    return {
        "employeeId": employee_id,
        "corp_id": provider.config.corp_id,
        "client_secret": provider.config.client_secret,
        "grant_type": provider.config.grant_type,
    }
