from hr_agent.constants.leave_rules import (
    SKIP_RESTDAY_MAP,
    HOLIDAY_TYPE_CODE,
    LEAVE_GENDER_MAP,
    REST_SHIFT_PREFIXES,
)
from hr_agent.constants.page_codes import PAGE_CODES
from hr_agent.constants.phrases import PHRASES


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
              "cancel_leave", "consult_not_ready"]:
        assert k in PHRASES and PHRASES[k]
