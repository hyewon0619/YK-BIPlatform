from datetime import date

import pytest

from app.db import query, scattered_dates
from app.services import decompose, monitoring
from app.services.monitoring import BY_KEY, score


def test_score_uses_z_and_change_with_their_own_thresholds():
    calls = BY_KEY["calls"]
    hist = [100, 102, 98, 100, 101, 99]
    s = score(calls, 60, hist)
    assert s["unit"] == "%" and s["delta"] == pytest.approx(40.0, abs=0.1)
    assert s["score"] >= 1 and s["candidate"]
    rate = BY_KEY["contract_rate"]
    r = score(rate, 30.0, [42.0, 38.0, 41.0, 39.0])
    assert r["unit"] == "%p" and r["delta"] == pytest.approx(10.0, abs=0.1)


def test_volatile_metric_still_surfaces_on_large_change():
    # 원래 출렁이는 지표는 z 가 작다. 그래도 30~40% 빠지면 변화폭 기준으로 올라와야 한다.
    v = score(BY_KEY["value_per_contract"], 3_200_000, [3_500_000, 7_000_000, 3_200_000, 7_500_000, 3_800_000])
    assert v["z"] < 1.5 and v["candidate"]


def test_small_relative_change_is_never_a_candidate():
    s = score(BY_KEY["calls"], 108, [100, 100, 100, 100.5])
    assert s["score"] >= 1 and not s["candidate"]


def test_at_most_three_highlights_and_planted_anomalies_found():
    for d in (date(2025, 3, 10), date(2026, 4, 14), date(2025, 6, 24)):
        h = monitoring.highlights(d)
        assert len(h["highlights"]) <= 3
    assert any(x["metric"] == "calls" and x["direction"] == "하락" for x in monitoring.highlights(date(2025, 3, 10))["highlights"])
    bulk = monitoring.highlights(date(2026, 4, 14))["highlights"]
    assert any(x["metric"] == "value_per_contract" and x["direction"] == "하락" for x in bulk)


def test_one_snapshot_query_per_screen(monkeypatch):
    calls = []
    real = monitoring.query
    monkeypatch.setattr(monitoring, "query", lambda *a, **k: calls.append(1) or real(*a, **k))
    monitoring.highlights(date(2026, 9, 14))
    assert len(calls) == 1


def test_excluding_advisory_and_low_amount_is_flagged_unofficial():
    official = monitoring.highlights(date(2026, 4, 14))
    filtered = monitoring.highlights(date(2026, 4, 14), exclude=True)
    assert official["official"] and not filtered["official"]
    assert filtered["values"]["contracts"] < official["values"]["contracts"]


def test_weekly_and_monthly_use_completed_periods():
    assert monitoring.periods(date(2026, 9, 15), "weekly")[0] == (date(2026, 9, 7), date(2026, 9, 13))
    assert monitoring.periods(date(2026, 9, 15), "monthly")[0] == (date(2026, 8, 1), date(2026, 8, 31))


def test_scattered_date_condition_matches_plain_in():
    days = [date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 24)]
    sql, params = scattered_dates("call_date", days)
    with_range = query(f"SELECT COUNT(*) AS n FROM consultation WHERE {sql}", params)[0]["n"]
    plain = query("SELECT COUNT(*) AS n FROM consultation WHERE call_date IN ('2026-08-03','2026-08-10','2026-08-24')")[0]["n"]
    assert with_range == plain > 0


@pytest.mark.parametrize("metric", ["calls", "contracts", "revenue", "value_per_contract", "contract_rate"])
@pytest.mark.parametrize("dimension", ["retain_type", "case_major", "channel", "lawyer", "amount_bucket"])
def test_contributions_sum_to_the_difference(metric, dimension):
    if metric == "contract_rate" and dimension in decompose.CONTRACT_ONLY_DIMS:
        with pytest.raises(ValueError):
            decompose.breakdown(date(2026, 8, 19), metric, dimension)
        return
    b = decompose.breakdown(date(2026, 8, 19), metric, dimension)
    assert b["sum_of_contributions"] == pytest.approx(b["difference"], abs=0.05 * max(1, len(b["items"])))


def test_value_per_contract_splits_exactly_into_amount_and_count():
    b = decompose.breakdown(date(2026, 4, 14), "value_per_contract", "retain_type")
    e = b["effects"]
    assert e["amount_effect"] + e["count_effect"] == pytest.approx(b["difference"], abs=0.5)
    assert b["items"][0]["value"] in ("착수금", "착수금+성공보수", "성공보수만")


def test_rate_rows_split_into_mix_and_conversion_with_mean_subtracted():
    b = decompose.breakdown(date(2025, 6, 24), "contract_rate", "consult_type")
    assert b["sum_of_contributions"] == pytest.approx(b["difference"], abs=0.05)
    for it in b["items"]:
        assert it["mix_effect"] + it["conversion_effect"] == pytest.approx(it["contribution"], abs=0.01)
    # 평균보다 전환율이 낮은 집단의 비중이 늘면 구성 효과는 음(-)이어야 한다.
    for it in b["items"]:
        share_up = it["now"]["visits"] / sum(x["now"]["visits"] for x in b["items"]) > \
            it["base"]["visits"] / sum(x["base"]["visits"] for x in b["items"])
        below_avg = (it["now"]["rate"] + it["base"]["rate"]) / 2 < (b["now"] + b["baseline"]) / 2
        if share_up and below_avg:
            assert it["mix_effect"] <= 0


def test_small_samples_are_grouped_but_total_kept():
    b = decompose.breakdown(date(2025, 6, 24), "contract_rate", "lawyer")
    assert any(it["value"] == decompose.OTHER for it in b["items"])
    assert b["sum_of_contributions"] == pytest.approx(b["difference"], abs=0.2)


def test_drill_down_into_major_category():
    b = decompose.breakdown(date(2026, 8, 19), "contracts", "case_minor", parent="이혼")
    assert {it["value"] for it in b["items"]} <= {"협의이혼", "재판이혼", "재산분할", "양육권"}


def test_response_carries_both_card_and_decomposition_baselines():
    b = decompose.breakdown(date(2026, 8, 19), "value_per_contract", "channel")
    assert "card_baseline" in b and "baseline" in b
