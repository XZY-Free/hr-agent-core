from packages.hr_domain.constants.leave_rules import (
    SKIP_RESTDAY_MAP,
    HOLIDAY_TYPE_CODE,
    LEAVE_GENDER_MAP,
    REST_SHIFT_PREFIXES,
)
from packages.hr_domain.constants.page_codes import PAGE_CODES
from packages.hr_domain.constants.phrases import PHRASES


def test_skip_restday_map_covers_27_types():
    assert len(SKIP_RESTDAY_MAP) == 27
    assert SKIP_RESTDAY_MAP["婚假"] is True        # 连续计算
    assert SKIP_RESTDAY_MAP["年休假"] is False     # 跳过休息日
    assert SKIP_RESTDAY_MAP["事假"] is False


def test_holiday_code_matches_legacy():
    assert HOLIDAY_TYPE_CODE["婚假"] == "A03"
    assert HOLIDAY_TYPE_CODE["年休假"] == "A31"
    assert HOLIDAY_TYPE_CODE["陪产假"] == "A08"
    assert set(HOLIDAY_TYPE_CODE) == set(SKIP_RESTDAY_MAP)  # 两表覆盖同一批假期


def test_gender_map():
    assert LEAVE_GENDER_MAP["产假"] == "F"
    assert LEAVE_GENDER_MAP["陪产假"] == "M"
    assert len(LEAVE_GENDER_MAP) == 9


def test_page_codes():
    assert PAGE_CODES["我的异常"] == "exception"
    assert len(PAGE_CODES) == 12


def test_rest_shift_prefixes_present():
    assert isinstance(REST_SHIFT_PREFIXES, tuple) and len(REST_SHIFT_PREFIXES) >= 1


def test_phrases_keys_present():
    for k in ["rest_day", "not_scheduled", "no_permission", "handoff",
              "cancel_leave"]:
        assert k in PHRASES and PHRASES[k]


def test_handoff_phrase_does_not_bounce_user_back():
    """转人工话术不能反过来让用户再说一次"转人工"。

    旧工作流没有转接动作，只能输出引导语让用户说出前端识别的关键词，于是
    用户说"转人工"后被回"请您回复转人工"——死循环。智能体直接确认转接。
    """
    assert "请您回复" not in PHRASES["handoff"]
    assert "转接" in PHRASES["handoff"]


def test_no_stale_coming_soon_phrase():
    """咨询 Agent 二期已上线，"敬请期待"占位话术不该再存在。"""
    assert "consult_not_ready" not in PHRASES
    assert all("敬请期待" not in v for v in PHRASES.values())
