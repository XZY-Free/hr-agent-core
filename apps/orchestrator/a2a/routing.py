"""冻结优先级的确定性路由，不由模型选择远程Agent。"""

import re
from enum import Enum


class RouteTarget(str, Enum):
    LOCAL = "local"
    CONSULT = "consult"
    EMPLOYEE_DATA = "employee_data"


_LEAVE_ACTION = re.compile(
    r"(?:请假|请一天|申请.{0,6}假|补登|改成后天|改成明天|"
    r"(?:我要|我想|帮我|替我).{0,6}(?:请|申请|办理).{0,12}假)"
)
_LEAVE_CONTINUATION = re.compile(r"^(?:确认|是的|对|改成后天|改成明天|取消)$")
_CANCEL = re.compile(r"取消|撤回|销假")
_EMPLOYEE_DATA = re.compile(
    r"(?:我|我的|本人|帮我).{0,12}(?:余额|几天年假|几天年休假|医疗期|工龄|参工|年假.{0,5}折算)"
)
_CROSS_EMPLOYEE_DATA = re.compile(
    r"(?:员工|同事|他|她|别人|工号|EMP[-_]?\d+).{0,16}"
    r"(?:余额|几天年假|几天年休假|医疗期|工龄|参工|年假.{0,5}折算)",
    re.IGNORECASE,
)
_PAGE = re.compile(r"^(?:打开|进入|跳转|查看).{0,20}(?:明细|排班|申请|信息|记录|统计|表单|余额)")
_HANDOFF = re.compile(r"转人工|找客服|投诉")
_GREETING = re.compile(r"^(?:你好|您好|嗨|hi|hello|谢谢|再见)[！!。.？?]*$", re.IGNORECASE)
_PROVINCE_ONLY = re.compile(
    r"^(?:北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|"
    r"山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|内蒙古|广西|"
    r"西藏|宁夏|新疆|香港|澳门|台湾)[省市区]?$"
)


class DeterministicRouteTable:
    def __init__(self):
        self._pending: dict[tuple[str, str], RouteTarget] = {}

    def decide(self, text: str, *, user_id: str, session_id: str) -> RouteTarget:
        message = text.strip()
        if _CANCEL.search(message) or _LEAVE_ACTION.search(message) or _LEAVE_CONTINUATION.search(message):
            return RouteTarget.LOCAL
        if _CROSS_EMPLOYEE_DATA.search(message) or _EMPLOYEE_DATA.search(message):
            return RouteTarget.EMPLOYEE_DATA
        if _PAGE.search(message) or _HANDOFF.search(message) or _GREETING.search(message):
            return RouteTarget.LOCAL
        pending = self._pending.get((user_id, session_id))
        if pending is not None:
            return pending
        if _PROVINCE_ONLY.fullmatch(message):
            return RouteTarget.LOCAL
        return RouteTarget.CONSULT

    def record_remote_status(
        self,
        *,
        user_id: str,
        session_id: str,
        target: RouteTarget,
        status: str,
    ) -> None:
        key = (user_id, session_id)
        if status == "need_more_information":
            self._pending[key] = target
        else:
            self._pending.pop(key, None)
