"""页面跳转码表，数据源：旧「测试-AI助手能力拓展」意图分类（迁移梳理报告 §3.5）。"""
PAGE_CODES: dict[str, str] = {
    "我的异常": "exception", "销假申请": "request-sick-leave", "我的信息": "my-info",
    "移动排班": "mobile-schedule", "打卡明细": "punch-details",
    "原始打卡记录": "punch-card-records", "我的排班": "scheduling",
    "考勤统计": "attendance-statistics", "加班申请": "request-overtime",
    "我的表单": "my-forms", "团队考勤": "team-attendance", "团队假期余额": "leave-quota",
}
