from datetime import date

import pytest

from app.db import query, query_one
from app.services import forecast, success_fee

AS_OF = date(2026, 9, 15)


def test_overdue_probability_table():
    assert forecast.overdue_probability(0, True) == 0.8
    assert forecast.overdue_probability(1, True) == 0.1
    assert forecast.overdue_probability(10, True) == 0.1
    assert forecast.overdue_probability(11, True) == 0.0
    # 기한 전이어도 최근 90일 납부 이력이 없으면 회수 확률은 바닥이다.
    assert forecast.overdue_probability(0, False) == 0.0


def test_forecast_is_sum_of_three_parts_and_achievement():
    r = forecast.revenue(AS_OF)
    assert r["forecast"] == r["confirmed"]["total"] + r["scheduled"]["expected"] + r["new_inflow"]["value"]
    assert r["achievement"] == pytest.approx(r["forecast"] / r["target"] * 100, abs=0.1)
    assert r["color"] == forecast.achievement_color(r["achievement"])
    assert [forecast.achievement_color(x) for x in (100, 99.9, 95, 94.9)] == ["green", "orange", "orange", "red"]


def test_refunds_enter_confirmed_as_negative_line():
    c = forecast.confirmed(date(2026, 1, 1), date(2026, 8, 31))
    assert c["refund"] < 0
    assert c["total"] == c["same_day"] + c["collected"] + c["refund"]


def test_offline_and_abnormal_payments_are_excluded():
    start = AS_OF.replace(day=1).isoformat()
    everything = query_one(
        "SELECT SUM(amount) AS s FROM installment WHERE paid_date BETWEEN :a AND :b",
        {"a": start, "b": AS_OF.isoformat()})["s"]
    eligible = forecast.confirmed(AS_OF.replace(day=1), AS_OF)
    assert eligible["same_day"] + eligible["collected"] < everything
    leaked = query_one(
        """SELECT COUNT(*) AS n FROM installment i JOIN engagement e ON e.id = i.engagement_id
           JOIN consultation c ON c.id = e.id
           WHERE i.paid_date BETWEEN :a AND :b AND (c.referrer IS NOT NULL OR e.pay_status <> '정상')""",
        {"a": start, "b": AS_OF.isoformat()})["n"]
    assert leaked > 0  # 제외 대상이 실제로 데이터에 있다.


def test_scheduled_buckets_add_up():
    s = forecast.scheduled(AS_OF.replace(day=1), AS_OF, date(2026, 9, 30))
    assert sum(b["principal"] for b in s["buckets"]) == s["principal"]
    assert s["uncollected_expected"] == s["principal"] - s["expected"]
    assert next(b for b in s["buckets"] if b["bucket"] == "10일 초과·장기 미납")["expected"] == 0


def test_new_inflow_counts_zero_days_and_starts_tomorrow():
    n = forecast.new_inflow(AS_OF, date(2026, 9, 30))
    # 일요일은 계약이 없다. 그날도 0 건으로 평균에 들어가야 한다.
    assert n["weekday_avg"][6] == 0.0
    # 오늘(15일)은 확정 입금에 있으니 남은 날은 16~30일이다.
    holidays = {r["day"] for r in query("SELECT day FROM holiday")}
    expected = 0.0
    for day in range(16, 31):
        d = date(2026, 9, day)
        expected += n["weekday_avg"][d.weekday()] * (0.5 if d.isoformat() in holidays else 1.0)
    assert n["expected_contracts"] == pytest.approx(expected, abs=0.1)
    assert 0 <= n["pay_ratio"] <= 1


def test_success_fee_backoff_and_bounds():
    est = success_fee.estimate()
    assert 0 < est["expected"] < est["pending_max"]
    assert set(est["levels_used"]) <= {"minor·consult_type", "minor", "major", "전체", "표본 없음"}


def test_past_as_of_does_not_see_later_payments():
    # 8월 15일로 되돌려 보면, 그 뒤에 들어온 회차는 아직 미납이어야 한다.
    s = forecast.scheduled(date(2026, 8, 1), date(2026, 8, 15), date(2026, 8, 31))
    assert s["principal"] > 0


def test_mid_month_backtest_error_is_small():
    bt = forecast.backtest(AS_OF, months=6)
    assert bt["mape"] < 15
    assert all(r["forecast"] > 0 and r["actual"] > 0 for r in bt["months"])
