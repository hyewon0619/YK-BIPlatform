"""당월 매출 예측 — pacing(진척률) 방식.

월중에 "이번 달 얼마나 나올까"를 묻는 상황을 푼다. 회귀 모델을 붙이는
대신, 과거 달들이 **월의 D일까지 월 전체의 몇 %를 채웠는지**를 모아
그 중앙값으로 현재 실적을 나눈다.

    예측 = 이번 달 D일까지 누적 / median(과거 달들의 D일 진척률)

이 방식을 고른 이유:
  - 월 길이·요일 배치·계절성이 진척률 안에 이미 녹아 있다.
  - 과거 달 수가 20개 남짓이라 파라미터 많은 모델은 과적합된다.
  - 왜 그 숫자가 나왔는지 실무자에게 설명할 수 있다. BI 에서는 이게 중요하다.

구간 추정은 과거 진척률의 25/75 분위수를 그대로 뒤집어 쓴다.
진척률이 낮게 잡히면 예측은 높아지므로 분위수가 교차하는 점에 주의.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from ..db import query


def _month_bounds(target: date) -> tuple[date, date]:
    last_day = calendar.monthrange(target.year, target.month)[1]
    return date(target.year, target.month, 1), date(target.year, target.month, last_day)


def _daily_revenue(start: date, end: date) -> dict[str, int]:
    rows = query(
        """
        SELECT contract_date AS date, COALESCE(SUM(contract_amount), 0) AS revenue
        FROM consultation
        WHERE contract_date BETWEEN :start AND :end
        GROUP BY contract_date
        """,
        {"start": start.isoformat(), "end": end.isoformat()},
    )
    return {r["date"]: r["revenue"] for r in rows}


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


def _pace_ratios(as_of: date, months_back: int) -> list[float]:
    """과거 달들의 '같은 일자까지 누적 / 월 전체' 비율."""
    ratios: list[float] = []
    cursor = as_of.replace(day=1)

    for _ in range(months_back):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        m_start, m_end = _month_bounds(cursor)
        daily = _daily_revenue(m_start, m_end)
        month_total = sum(daily.values())
        if month_total <= 0:
            continue

        # 짧은 달이면 그 달의 마지막 날까지만 누적한다.
        cutoff_day = min(as_of.day, m_end.day)
        cutoff = date(cursor.year, cursor.month, cutoff_day)
        partial = sum(rev for d, rev in daily.items() if d <= cutoff.isoformat())
        ratios.append(partial / month_total)

    return ratios


def revenue(as_of: date, months_back: int = 12) -> dict:
    """as_of 시점에서 그 달 전체 매출을 예측한다."""
    m_start, m_end = _month_bounds(as_of)
    daily = _daily_revenue(m_start, as_of)
    month_to_date = sum(daily.values())

    ratios = _pace_ratios(as_of, months_back)
    if not ratios or month_to_date == 0:
        return {
            "as_of": as_of.isoformat(),
            "month": as_of.strftime("%Y-%m"),
            "month_to_date": month_to_date,
            "forecast": month_to_date,
            "lower": month_to_date,
            "upper": month_to_date,
            "pace_ratio": None,
            "confidence": "예측 불가 (참고 데이터 부족)",
            "samples": len(ratios),
        }

    median_ratio = _quantile(ratios, 0.5)
    p25, p75 = _quantile(ratios, 0.25), _quantile(ratios, 0.75)

    forecast = int(month_to_date / median_ratio) if median_ratio else month_to_date
    # 진척률이 높게 잡히면(p75) 남은 매출이 적다는 뜻 -> 예측 하한.
    lower = int(month_to_date / p75) if p75 else forecast
    upper = int(month_to_date / p25) if p25 else forecast

    # 표본이 적으면 숫자를 단정적으로 보여주지 않는다.
    if len(ratios) >= 12:
        confidence = "높음"
    elif len(ratios) >= 6:
        confidence = "보통"
    else:
        confidence = "참고용 (표본 부족)"

    return {
        "as_of": as_of.isoformat(),
        "month": as_of.strftime("%Y-%m"),
        "month_start": m_start.isoformat(),
        "month_end": m_end.isoformat(),
        "elapsed_days": as_of.day,
        "total_days": m_end.day,
        "month_to_date": month_to_date,
        "forecast": forecast,
        "lower": lower,
        "upper": upper,
        "pace_ratio": round(median_ratio, 4),
        "confidence": confidence,
        "samples": len(ratios),
    }


def revenue_history(as_of: date, months: int = 12) -> list[dict]:
    """지난 달들의 실제 월매출. 예측값과 나란히 그리기 위한 것."""
    out: list[dict] = []
    cursor = as_of.replace(day=1)
    for _ in range(months):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        m_start, m_end = _month_bounds(cursor)
        total = sum(_daily_revenue(m_start, m_end).values())
        out.append({"month": cursor.strftime("%Y-%m"), "revenue": total})
    out.reverse()
    return out
