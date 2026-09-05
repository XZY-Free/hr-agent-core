"""请假最终提交边界：只接受内部 LeaveForm（全取 authoritative 字段），走原有干跑/提交逻辑。

GAIA_DRY_RUN（默认 true）为 true 时不调提交接口，直接返回请假单 JSON——业务确认的
正式形态（智能体只输出请假单 JSON，由后端自行调盖亚提交接口）。
GAIA_DRY_RUN=false 走 _do_submit 直连提交，为示例实现，默认不启用。

本模块只保留唯一 finalize 入口与原有 _do_submit 边界；不再暴露旧扁平 submit_leave 的
模型权威路径（model 表达请求走 save_leave_draft）。不处理最终业务动作 JSON 的假实现
问题——那属于本工程包明确排除范围。
"""
from __future__ import annotations

import os

from packages.hr_domain.gaia.provider import GaiaProvider
from packages.hr_domain.schemas.leave_form import LeaveForm

# 提交接口路径/环境：接口文档到位后核对。
SUBMIT_PATH = os.getenv(
    "GAIA_SUBMIT_PATH",
    "/atd-webapi/api/gaiaStandard/leave/submitLeaveApply/{corp_id}",
)
SUBMIT_ENV = os.getenv("GAIA_SUBMIT_ENV", "sandbox")


def _dry_run_enabled() -> bool:
    return os.getenv("GAIA_DRY_RUN", "true").lower() in ("true", "1", "yes")


def _do_submit(form: LeaveForm, provider: GaiaProvider, employee_id: str) -> dict:
    """直连提交请假接口（GAIA_DRY_RUN=false 才走）。仅用于示例实现，字段映射待文档。

    凭据由服务端配置驱动（provider.raw_client），不把 secret 复制进 state；错误按安全
    类别脱敏，不 dump 原始响应/正文/理由到日志。
    """
    payload = form.to_submit_payload()
    try:
        client = provider.raw_client(SUBMIT_ENV)
        resp = client.request(
            SUBMIT_ENV, "POST",
            SUBMIT_PATH.format(corp_id=provider.config.corp_id),
            json_body=dict(payload, employeeId=employee_id),
            tenant=provider.config.corp_id,
        )
    except Exception:
        return {"submitted": False, "dry_run": False, "error_type": "submit_failed",
                "message": "提交请假单失败，请稍后重试或联系管理员。"}
    if not (resp.get("result") and resp.get("code") == 200):
        return {"submitted": False, "dry_run": False, "error_type": "submit_failed",
                "message": "提交请假单失败，请稍后重试或联系管理员。"}
    apply_id = (resp.get("data") or {}).get("applyId") if isinstance(resp.get("data"), dict) else None
    return {"submitted": True, "dry_run": False, "form": payload, "apply_id": apply_id}


def finalize_leave_submission(form: LeaveForm, provider: GaiaProvider, employee_id: str) -> dict:
    """最终提交边界：内部 LeaveForm 全取 authoritative 字段后走原有干跑/提交逻辑。

    - DAY 单位：GAIA_DRY_RUN（默认 true）时仅返回表单 JSON，对外语义冻结；日志不 dump
      payload（理由等隐私）。
    - HOUR 单位：最终 hour 动作协议本版本未授权重做，明确不支持（已保留 hour 草稿），
      绝不把 2 小时映成 2 天 leaveDays。
    """
    from packages.hr_domain.schemas.leave_draft import DurationUnit

    if form.duration_unit == DurationUnit.HOUR.value:
        return {"submitted": False, "dry_run": False, "error_type": "unsupported_hour",
                "message": "小时请假最终提交本版本暂不支持，已保留小时请假草稿。"}
    payload = form.to_submit_payload()
    if _dry_run_enabled():
        return {"submitted": False, "dry_run": True, "form": payload}
    return _do_submit(form, provider, employee_id)
