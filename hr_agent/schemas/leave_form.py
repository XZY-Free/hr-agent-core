"""请假单内部 schema。提交接口入参基础结构。"""
from pydantic import BaseModel

from hr_agent.constants.leave_rules import HOLIDAY_TYPE_CODE


class LeaveForm(BaseModel):
    type_name: str
    start_date: str   # yyyy-MM-dd
    end_date: str
    start_time: str   # HH:mm
    end_time: str
    leave_days: float  # 0.5 的整数倍
    reasons: str = ""

    def to_submit_payload(self) -> dict:
        """输出旧系统 leave_support 请假单字段结构（提交接口入参基础）。"""
        return {
            "typeCode": HOLIDAY_TYPE_CODE.get(self.type_name, ""),
            "typeName": self.type_name,
            "startDate": self.start_date, "startTime": self.start_time,
            "endDate": self.end_date, "endTime": self.end_time,
            "reasons": self.reasons, "leaveDays": self.leave_days,
        }
