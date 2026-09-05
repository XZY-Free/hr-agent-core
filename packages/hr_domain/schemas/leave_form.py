"""请假单内部 schema。提交接口入参基础结构。"""
import math

from pydantic import BaseModel

from packages.hr_domain.constants.leave_rules import HOLIDAY_TYPE_CODE
from packages.hr_domain.schemas.leave_draft import DurationUnit, LeaveDraftState


class LeaveForm(BaseModel):
    type_name: str
    start_date: str   # yyyy-MM-dd
    end_date: str
    start_time: str   # HH:mm
    end_time: str
    leave_days: float = 0.0  # 0.5 的整数倍；仅 DAY 单位有意义，HOUR 不映成 leaveDays
    reasons: str = ""
    duration_value: float | None = None      # 权威时长（交易事实，day/hour 分开）
    duration_unit: str | None = None          # day / hour

    @classmethod
    def from_authoritative(cls, draft: LeaveDraftState) -> "LeaveForm":
        """从权威草稿构造最终请假单：全部字段只取 authoritative 值。

        WP-02 最终边界（严格）：只有权威字段完整才可构造，绝不空缺回退 ''/0。
        DAY 单位映射 leaveDays；HOUR 单位保留 duration_value/unit，leaveDays 保持 0，
        由 finalize 边界明确不支持最终 hour 动作（绝不把 2 小时映成 2 天）。
        reason 为空字符串（用户没说则保持空，不补"个人事务"；用户提供则逐字保留）。
        """
        unit = draft.authoritative_duration_unit
        if not all((
            draft.normalized_type_name,
            draft.authoritative_start_date,
            draft.authoritative_end_date,
            draft.authoritative_start_time,
            draft.authoritative_end_time,
            draft.authoritative_start_date_source,
            draft.authoritative_end_date_source,
            draft.authoritative_start_time_source,
            draft.authoritative_end_time_source,
            draft.authoritative_duration_value_source,
            draft.authoritative_duration_unit_source,
        )) or draft.authoritative_duration_value is None or unit is None:
            raise ValueError("请假草稿权威字段不完整，无法构造最终请假单。")
        if unit not in (DurationUnit.DAY, DurationUnit.HOUR):
            raise ValueError("请假时长单位只支持 day/hour。")
        days = float(draft.authoritative_duration_value)
        if not (math.isfinite(days) and days > 0):
            raise ValueError("请假时长必须为有限且大于 0 的数值。")
        leave_days = days if unit is DurationUnit.DAY else 0.0
        return cls(
            type_name=draft.normalized_type_name,
            start_date=draft.authoritative_start_date,
            end_date=draft.authoritative_end_date,
            start_time=draft.authoritative_start_time,
            end_time=draft.authoritative_end_time,
            leave_days=leave_days,
            reasons=draft.reason or "",
            duration_value=days,
            duration_unit=unit.value,
        )

    def to_submit_payload(self) -> dict:
        """输出旧系统 leave_support 请假单字段结构（提交接口入参基础；仅 DAY 有 leaveDays）。

        仅 DAY 单位可输出；HOUR 以 0 天代替是明确错误，直接 ValueError（不留旁路）。
        """
        if self.duration_unit != DurationUnit.DAY.value:
            raise ValueError("仅 DAY 单位可输出提交 payload；HOUR 不允许以 0 天代替。")
        return {
            "typeCode": HOLIDAY_TYPE_CODE.get(self.type_name, ""),
            "typeName": self.type_name,
            "startDate": self.start_date, "startTime": self.start_time,
            "endDate": self.end_date, "endTime": self.end_time,
            "reasons": self.reasons, "leaveDays": self.leave_days,
        }
