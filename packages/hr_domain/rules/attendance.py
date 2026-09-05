"""考勤量化计算确定性规则（WP-04）。

旧 FastGPT 中多个 LLM 节点负责的"迟到扣款/早退/旷工"计算，不能用 LLM 做算术。
本模块统一：
- 单位解析（分钟/小时/半小时）；
- 一般异常 10 分钟档阶梯（每 10 分钟 20 元，不足 10 按 10）；
- 10 分钟（含）以内月度豁免（单次 <=10 分钟，月度前 2 次免，超过扣 20）；
  迟到与早退各自维护已用免扣次数，单批内成功免扣一条会将该池计数 +1，两池互不影响；
- 严重迟到/早退（60<=m<240 旷工 0.5；m>=240 旷工 1），严重不再产生金额；
- 多记录按原顺序累计，审计留痕。

严重与否看原始实际分钟数；51~59 分钟即使取整到 60 也仍是一般异常。
"""

from __future__ import annotations

import math

from packages.hr_domain.schemas.attendance import (
    AttendanceInput,
    AttendanceItemResult,
    AttendanceKind,
    AttendanceRecord,
    AttendanceResult,
)

# 每分钟档位：40 元档 = 10 分钟（20 元/10 分钟）
PER_BUCKET_AMOUNT = 20.0
BUCKET_MINUTES = 10
MONTHLY_EXEMPT_LIMIT = 2      # 每月 10 分钟（含）内前 2 次免
SEVERE_MIN = 60
SEVERE_ABSENCE_DAYS = 0.5
FULL_DAY_ABSENCE_MIN = 240
FULL_DAY_ABSENCE_DAYS = 1.0


def parse_duration_minutes(expression: str) -> int | None:
    """把"10分钟/十分钟/半小时/1小时/1.5小时"换算为分钟。

    非法（0、负数、模糊"大概半小时/迟到了一会/有点晚/没有数值"）返回 None，
    由调用方返回 insufficient_attendance_duration。
    """
    if not expression:
        return None
    text = expression.strip()
    if not text:
        return None
    # 模糊词直接拒绝，不猜。
    for vague in ("大概", "一会", "有点", "约", "左右"):
        if vague in text:
            return None
    if text[0] == "-":
        return None
    m = _match_num(text)
    value = m[0] if m else None
    if "半小时" in text or "半个小时" in text:
        minutes = 30
    elif "小时" in text or "时" in text or "小時" in text:
        if value is None:
            return None
        minutes = value * 60
    elif "分" in text or "分钟" in text:
        if value is None:
            return None
        minutes = value
    else:
        if value is None:
            return None
        minutes = value
    minutes = round(float(minutes))
    if minutes <= 0:
        return None
    return minutes


_CN_NUM = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _match_num(text: str) -> tuple[float] | None:
    import re
    # 阿拉伯数字
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if match:
        return (float(match.group(1)),)
    # 中文数字（十/十一/二十等）
    cn_match = re.search(r"([零一二两三四五六七八九十]+)", text)
    if not cn_match:
        return None
    cn = cn_match.group(1)
    if cn == "十":
        return (10.0,)
    if len(cn) == 2 and cn[1] == "十":
        return (float(_CN_NUM[cn[0]]) * 10,)
    if len(cn) == 2 and cn[0] == "十":
        return (float(10 + _CN_NUM[cn[1]]),)
    if len(cn) == 3 and cn[1] == "十":
        return (float(_CN_NUM[cn[0]] * 10 + _CN_NUM[cn[2]]),)
    if cn in _CN_NUM:
        return (float(_CN_NUM[cn]),)
    return None


def calculate_attendance(input: AttendanceInput) -> AttendanceResult:
    result = AttendanceResult()
    ctx = input.exempt_context
    late_count: int | None = ctx.late_prior_exempt if ctx is not None else None
    early_count: int | None = ctx.early_leave_prior_exempt if ctx is not None else None
    # 负数/非法月度免扣次数 fail closed，绝不当作 0。
    if (
        (late_count is not None and late_count < 0)
        or (early_count is not None and early_count < 0)
    ):
        result.error_code = "invalid_monthly_exempt_context"
        result.error_message = "本月免扣次数非法。"
        return result
    for idx, record in enumerate(input.records):
        prior = _pool_prior(late_count, early_count, record.kind)
        item = _evaluate_record(record, prior=prior, sequence=idx + 1)
        result.records.append(item)
        result.total_deduction += item.deduction
        result.total_absence_days += item.absence_days
        if item.needed_context:
            result.unresolved_context.append(
                f"第{idx + 1}条{_kind_label(record.kind)}缺本月免扣上下文"
            )
        if item.error_code:
            result.error_code = item.error_code
            result.error_message = item.error_message
            return result
        # 免扣一次：把该池本轮已用次数 +1（未知或已超限都不会进入免扣分支）。
        if item.exemption_applied:
            if record.kind is AttendanceKind.LATE and late_count is not None:
                late_count += 1
            elif record.kind is AttendanceKind.EARLY_LEAVE and early_count is not None:
                early_count += 1
    return result


def _evaluate_record(
    record: AttendanceRecord,
    *,
    prior: int | None,
    sequence: int,
) -> AttendanceItemResult:
    """评估单条异常记录；prior 为该迟到/早退池本轮的已用免扣次数（未知为 None）。"""
    minutes = record.duration_minutes
    if minutes <= 0:
        return AttendanceItemResult(
            sequence=sequence, kind=record.kind, original_minutes=minutes,
            chargeable_bucket=None, deduction=0.0, absence_days=0.0,
            exemption_applied=False, is_severe=False,
            error_code="insufficient_attendance_duration",
            error_message="迟到/早退时长无效。",
        )

    # 严重迟到/早退：只看原始实际分钟数。
    if minutes >= FULL_DAY_ABSENCE_MIN:
        return AttendanceItemResult(
            sequence=sequence, kind=record.kind, original_minutes=minutes,
            chargeable_bucket=None, deduction=0.0,
            absence_days=FULL_DAY_ABSENCE_DAYS, exemption_applied=False,
            is_severe=True,
        )
    if minutes >= SEVERE_MIN:
        return AttendanceItemResult(
            sequence=sequence, kind=record.kind, original_minutes=minutes,
            chargeable_bucket=None, deduction=0.0,
            absence_days=SEVERE_ABSENCE_DAYS, exemption_applied=False,
            is_severe=True,
        )

    # 10 分钟（含）以内：月度小额豁免判断。
    if minutes <= BUCKET_MINUTES:
        if prior is None:
            # 缺该池月度上下文，不猜第一次或第三次 → 需追问。
            return AttendanceItemResult(
                sequence=sequence, kind=record.kind, original_minutes=minutes,
                chargeable_bucket=BUCKET_MINUTES, deduction=0.0,
                absence_days=0.0, exemption_applied=False,
                is_severe=False, needed_context=True,
            )
        if prior < MONTHLY_EXEMPT_LIMIT:
            return AttendanceItemResult(
                sequence=sequence, kind=record.kind, original_minutes=minutes,
                chargeable_bucket=BUCKET_MINUTES, deduction=0.0,
                absence_days=0.0, exemption_applied=True,
                is_severe=False,
            )
        # 超过 2 次：按 10 分钟档扣款。
        return AttendanceItemResult(
            sequence=sequence, kind=record.kind, original_minutes=minutes,
            chargeable_bucket=BUCKET_MINUTES, deduction=PER_BUCKET_AMOUNT,
            absence_days=0.0, exemption_applied=False,
            is_severe=False,
        )

    # 一般异常（11~59 分钟）：每 10 分钟 20 元，不足 10 按 10。
    bucket = int(math.ceil(minutes / BUCKET_MINUTES)) * BUCKET_MINUTES
    deduction = (bucket // BUCKET_MINUTES) * PER_BUCKET_AMOUNT
    # 51~59 分钟取整到 60 计费桶，但仍是"未达 60 分钟一般异常"（is_severe=False）。
    return AttendanceItemResult(
        sequence=sequence, kind=record.kind, original_minutes=minutes,
        chargeable_bucket=bucket, deduction=deduction,
        absence_days=0.0, exemption_applied=False,
        is_severe=False,
    )


def _pool_prior(late_count: int | None, early_count: int | None, kind: AttendanceKind) -> int | None:
    """按迟到/早退各自取池内已用免扣计数（每池独立；未提供记为 None/未知）。"""
    if kind is AttendanceKind.LATE:
        return late_count
    return early_count


def _kind_label(kind: AttendanceKind) -> str:
    return "迟到" if kind is AttendanceKind.LATE else "早退"
