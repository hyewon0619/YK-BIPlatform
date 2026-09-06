"""퍼널 지표 — 콜 -> 예약 -> 방문 -> 계약.

지표 정의(전부 이 파일 안에서 끝난다):
  콜     call_date 가 그 날인 상담 건수
  예약   그 날 인입된 콜 중 reserved_date 가 채워진 건수
  방문   그 날 인입된 콜 중 visit_date 가 채워진 건수
  계약   그 날 인입된 콜 중 contract_date 가 채워진 건수

전환율은 앞 단계 대비로 계산한다(예약률 = 예약/콜, 방문률 = 방문/예약,
계약률 = 계약/방문). 콜 대비 최종 계약률은 별도로 overall_rate 로 낸다.

"콜 인입일 기준"으로 코호트를 묶는 게 핵심이다. 계약일 기준으로 세면
같은 날의 콜과 계약이 서로 다른 모수라서 전환율이 왜곡된다.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..db import query, query_one

_FUNNEL_SELECT = """
    SELECT
        COUNT(*)                                            AS calls,
        SUM(CASE WHEN reserved_date IS NOT NULL THEN 1 END) AS reservations,
        SUM(CASE WHEN visit_date    IS NOT NULL THEN 1 END) AS visits,
        SUM(CASE WHEN contract_date IS NOT NULL THEN 1 END) AS contracts,
        COALESCE(SUM(contract_amount), 0)                   AS revenue,
        COALESCE(SUM(success_fee), 0)                       AS success_fee
    FROM consultation
    WHERE call_date BETWEEN :start AND :end
"""


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def _shape(row: dict) -> dict:
    calls = row.get("calls") or 0
    reservations = row.get("reservations") or 0
    visits = row.get("visits") or 0
    contracts = row.get("contracts") or 0
    revenue = row.get("revenue") or 0
    return {
        "calls": calls,
        "reservations": reservations,
        "visits": visits,
        "contracts": contracts,
        "revenue": revenue,
        "success_fee": row.get("success_fee") or 0,
        "reservation_rate": _rate(reservations, calls),
        "visit_rate": _rate(visits, reservations),
        "contract_rate": _rate(contracts, visits),
        "overall_rate": _rate(contracts, calls),
        # 부가가치: 계약 1건당 평균 계약금액
        "value_per_contract": int(revenue / contracts) if contracts else 0,
        # 콜당 매출: 마케팅 효율을 보는 지표
        "revenue_per_call": int(revenue / calls) if calls else 0,
    }


def snapshot(target: date) -> dict:
    """하루치 퍼널 스냅샷."""
    row = query_one(_FUNNEL_SELECT, {"start": target.isoformat(), "end": target.isoformat()})
    return {"date": target.isoformat(), **_shape(row)}


def period(start: date, end: date) -> dict:
    """기간 합계 퍼널."""
    row = query_one(_FUNNEL_SELECT, {"start": start.isoformat(), "end": end.isoformat()})
    return {"start": start.isoformat(), "end": end.isoformat(), **_shape(row)}


def weekday_trend(target: date, weeks: int = 12) -> dict:
    """같은 요일로 거슬러 올라가며 weeks 주치 스냅샷을 모은다.

    요일 효과가 워낙 커서 "어제 대비"는 의미가 없다. 전주 같은 요일들과
    비교해야 진짜 변화가 보인다. 프론트는 이 값들의 평균을 기준선으로 쓴다.
    """
    history = []
    for i in range(1, weeks + 1):
        past = target - timedelta(weeks=i)
        history.append(snapshot(past))
    history.reverse()

    baseline: dict[str, float] = {}
    if history:
        for key in ("calls", "reservations", "visits", "contracts", "revenue", "overall_rate"):
            baseline[key] = round(sum(h[key] for h in history) / len(history), 1)

    current = snapshot(target)
    deltas = {}
    for key, base in baseline.items():
        deltas[key] = round((current[key] - base) / base * 100, 1) if base else 0.0

    return {
        "current": current,
        "history": history,
        "baseline": baseline,
        "delta_pct": deltas,
        "weeks": weeks,
    }


def daily_series(start: date, end: date) -> list[dict]:
    """일자별 시계열. 상담이 하루도 없는 날은 애초에 없어서 그대로 낸다."""
    rows = query(
        """
        SELECT
            call_date                                           AS date,
            COUNT(*)                                            AS calls,
            SUM(CASE WHEN reserved_date IS NOT NULL THEN 1 END) AS reservations,
            SUM(CASE WHEN visit_date    IS NOT NULL THEN 1 END) AS visits,
            SUM(CASE WHEN contract_date IS NOT NULL THEN 1 END) AS contracts,
            COALESCE(SUM(contract_amount), 0)                   AS revenue
        FROM consultation
        WHERE call_date BETWEEN :start AND :end
        GROUP BY call_date
        ORDER BY call_date
        """,
        {"start": start.isoformat(), "end": end.isoformat()},
    )
    for r in rows:
        r["reservations"] = r["reservations"] or 0
        r["visits"] = r["visits"] or 0
        r["contracts"] = r["contracts"] or 0
        r["reservation_rate"] = _rate(r["reservations"], r["calls"])
        r["overall_rate"] = _rate(r["contracts"], r["calls"])
    return rows
