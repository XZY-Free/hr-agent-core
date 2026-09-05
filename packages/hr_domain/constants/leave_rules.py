"""业务规则资产，数据源：FastGPT 工作流原文（迁移梳理报告 §3.7 与快捷流程代码节点）。"""

# 27 类假期是否"连续计算（含休息日）"。True=连续自然日；False=按排班跳过休息日
SKIP_RESTDAY_MAP: dict[str, bool] = {
    # 连续计算（是）
    "婚假": True, "产假": True, "病假": True, "育儿假": True, "计划生育假": True,
    "无薪产假": True, "有薪产假": True, "子女护理假": True, "不定时员工日常休假": True,
    "产前假": True, "陪产假": True, "出差": True, "公出": True,
    # 跳过休息日（否）
    "丧假": False, "产检假": False, "非独生子女护理假": False, "事假": False,
    "调休假": False, "无薪侍产假": False, "80%病假": False, "调休假(综合工时)": False,
    "有薪侍产假": False, "年休假": False, "无薪假": False, "路程假": False,
    "全薪病假": False, "哺乳假": False,
}

# 假期名 → 盖亚 typeCode（旧工作流 holidayTypeMap 原文）
HOLIDAY_TYPE_CODE: dict[str, str] = {
    "婚假": "A03", "丧假": "A04", "产检假": "A05", "非独生子女护理假": "A48",
    "产假": "A06", "病假": "B01", "事假": "C01", "育儿假": "A47", "调休假": "A02",
    "无薪侍产假": "C03", "计划生育假": "A32", "80%病假": "B03", "无薪产假": "C02",
    "调休假(综合工时)": "A35", "有薪产假": "B04", "有薪侍产假": "B02",
    "子女护理假": "A37", "年休假": "A31", "不定时员工日常休假": "A43", "无薪假": "C04",
    "产前假": "A33", "路程假": "A40", "全薪病假": "A49", "陪产假": "A08",
    "哺乳假": "A09", "出差": "L01", "公出": "L02",
}

# 限性别假期（旧工作流 leaveGenderMap 原文），F=女 M=男；不在表内不限性别
LEAVE_GENDER_MAP: dict[str, str] = {
    "产检假": "F", "产假": "F", "无薪产假": "F", "有薪产假": "F", "产前假": "F",
    "哺乳假": "F", "无薪侍产假": "M", "有薪侍产假": "M", "陪产假": "M",
}

# 休息日班次 shiftCode 前缀（跳休判断用）
REST_SHIFT_PREFIXES = ("OFF", "off_day", "defaultOFF")

# 假期类型标准化别名（确定性规则，不由模型记忆）。仅口语→正式名。
TYPE_ALIASES: dict[str, str] = {
    "年假": "年休假",
    "调休": "调休假",
    "年休": "年休假",
    "事假": "事假",
    "病假": "病假",
    "婚假": "婚假",
    "陪产假": "陪产假",
    "育儿假": "育儿假",
    "丧假": "丧假",
}

# 已知假期类型 token（正式名 + 别名），按长度降序，用于最长非重叠匹配，避免
# "陪产假 ⊃ 产假"这类子串误报。
KNOWN_TYPE_TOKENS: tuple[str, ...] = tuple(sorted(
    {*SKIP_RESTDAY_MAP.keys(), *TYPE_ALIASES.keys(), *TYPE_ALIASES.values()},
    key=len, reverse=True,
))


def normalize_type_name(raw: str) -> str | None:
    """把口语假期名标准化为 SKIP_RESTDAY_MAP 的正式名；未知返回 None。"""
    candidate = raw.strip()
    hit = TYPE_ALIASES.get(candidate)
    if hit and hit in SKIP_RESTDAY_MAP:
        return hit
    if candidate in SKIP_RESTDAY_MAP:
        return candidate
    return None
