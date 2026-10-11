"""① 당월 매출 예측 — 온라인 신규 사건 입금이 월말에 얼마가 되고, 목표의 몇 % 인가.

월말 입금 = 확정 입금 + 연체 보정한 남은 납부 예정액 + 남은 날의 신규 계약 유입 추정.

    F = I_확정 + R_예정 + N_신규,   달성률 = F / 월 목표 × 100

학습 모델 대신 현업이 설명할 수 있는 규칙과 최근 28일 실측치로 만든다. 현업이 "왜 이 숫자인가"를
물으면 카드의 세 항목과 곱셈 하나로 답할 수 있어야 하기 때문이다.

대상: 소개자가 없는 온라인 신규 사건. 제외: 비정상 결제 상태(사임미반환·불확정·불성립·조건부·
지급명령), 오프라인(소개) 사건, 계약 해지 건, 성공보수(별도 화면에서 추정).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from ..db import query, query_one

#: 연체 구간별 납부 확률. 학습값이 아니라 현업 경험으로 정한 표이며, 실데이터로 튜닝할 대상이다.
OVERDUE_PROB = ((0, 0, 0.8), (1, 10, 0.1))
NO_PAYMENT_WINDOW_DAYS = 90
WINDOW_DAYS = 28            # 요일을 4번씩 포함하는 가장 짧은 창
HOLIDAY_FACTOR = 0.5
FALLBACK_PAY_RATIO = 0.72   # 표본이 없을 때 쓰는 계약 당일 지급률 경험치

#: 온라인 신규 사건 조건. 모든 항목이 이 정의 하나를 쓴다.
ELIGIBLE = """
    JOIN consultation c ON c.id = e.id
    JOIN channel ch     ON ch.id = c.channel_id
    WHERE c.referrer IS NULL AND ch.is_referral = 0
      AND e.pay_status = '정상' AND e.terminated = 0
"""


def overdue_probability(days_overdue: int, paid_recently: bool) -> float:
    """연체 구간별 납부 확률 P(d). 최근 90일간 납부 이력이 없으면 0 이다."""
    if not paid_recently:
        return 0.0
    for lo, hi, p in OVERDUE_PROB:
        if lo <= days_overdue <= hi:
            return p
    return 0.0


def _month_bounds(d: date) -> tuple[date, date]:
    return d.replace(day=1), d.replace(day=calendar.monthrange(d.year, d.month)[1])


def confirmed(start: date, as_of: date) -> dict:
    """확정 입금. 입금일이 선임일과 같으면 당일 착수금, 아니면 추심 입금. 사임 환불은 음수 라인."""
    row = query_one(
        f"""
        SELECT
          COALESCE(SUM(CASE WHEN i.paid_date = c.contract_date THEN i.amount END), 0) AS same_day,
          COALESCE(SUM(CASE WHEN i.paid_date <> c.contract_date THEN i.amount END), 0) AS collected
        FROM installment i JOIN engagement e ON e.id = i.engagement_id
        {ELIGIBLE}
          AND i.paid_date BETWEEN :start AND :as_of
        """,
        {"start": start.isoformat(), "as_of": as_of.isoformat()},
    )
    refund = query_one(
        f"""
        SELECT COALESCE(SUM(r.amount), 0) AS refund
        FROM refund r JOIN engagement e ON e.id = r.engagement_id
        JOIN consultation c ON c.id = e.id JOIN channel ch ON ch.id = c.channel_id
        WHERE c.referrer IS NULL AND ch.is_referral = 0 AND e.terminated = 0
          AND r.refund_date BETWEEN :start AND :as_of
        """,
        {"start": start.isoformat(), "as_of": as_of.isoformat()},
    )["refund"]
    total = row["same_day"] + row["collected"] + refund
    return {"same_day": row["same_day"], "collected": row["collected"], "refund": refund, "total": total}


def scheduled(start: date, as_of: date, end: date) -> dict:
    """추심 예정. 이번 달 납부 예정인 미납 회차 i 의 금액 × 연체 구간별 납부 확률 P(d_i).

    "미납"은 기준일 시점이다. 과거 날짜로 다시 조회할 때 그 뒤에 들어온 입금을 보면 안 된다.

    d_i 는 그 회차의 연체일수다(기한 전이면 0). 기한은 아직 안 지났어도 최근 90일간 납부 이력이 전혀
    없는 수임은 겉보기 연체 0일이어도 회수 확률이 사실상 바닥이라 0 으로 본다.
    """
    rows = query(
        f"""
        SELECT i.engagement_id, i.amount, i.due_date,
          (SELECT MAX(p.paid_date) FROM installment p
            WHERE p.engagement_id = i.engagement_id AND p.paid_date <= :as_of) AS last_paid
        FROM installment i JOIN engagement e ON e.id = i.engagement_id
        {ELIGIBLE}
          AND (i.paid_date IS NULL OR i.paid_date > :as_of) AND i.due_date BETWEEN :start AND :end
          AND c.contract_date <= :as_of
        """,
        {"start": start.isoformat(), "as_of": as_of.isoformat(), "end": end.isoformat()},
    )
    buckets = {"0일": [0, 0.0], "1~10일": [0, 0.0], "10일 초과·장기 미납": [0, 0.0]}
    expected = 0.0
    for r in rows:
        d = max(0, (as_of - date.fromisoformat(r["due_date"])).days)
        recent = bool(r["last_paid"]) and (as_of - date.fromisoformat(r["last_paid"])).days <= NO_PAYMENT_WINDOW_DAYS
        p = overdue_probability(d, recent)
        key = "0일" if p == 0.8 else "1~10일" if p == 0.1 else "10일 초과·장기 미납"
        buckets[key][0] += r["amount"]
        buckets[key][1] += r["amount"] * p
        expected += r["amount"] * p
    principal = sum(r["amount"] for r in rows)
    return {
        "principal": principal,
        "expected": int(round(expected)),
        "uncollected_expected": int(round(principal - expected)),
        "buckets": [{"bucket": k, "principal": v[0], "expected": int(round(v[1]))} for k, v in buckets.items()],
    }


def new_inflow(as_of: date, end: date) -> dict:
    """신규 유입 = 남은 날의 예상 계약 수 × 최근 평균 약정금 × 계약 당일 지급률.

    남은 날은 내일부터 센다. 오늘 들어온 착수금은 이미 확정 입금에 있어서 이중으로 세지 않는다.
    요일 평균은 계약이 없던 날도 0 건으로 넣어 낸다. 빠뜨리면 계약 수가 높게 추정된다.
    """
    win_start = as_of - timedelta(days=WINDOW_DAYS - 1)
    rows = query(
        f"""
        SELECT c.contract_date AS day, c.contract_amount AS amount,
          COALESCE((SELECT SUM(i.amount) FROM installment i
                    WHERE i.engagement_id = e.id AND i.paid_date = c.contract_date), 0) AS paid_same_day
        FROM engagement e
        {ELIGIBLE}
          AND c.contract_date BETWEEN :start AND :as_of AND c.contract_amount > 0
        """,
        {"start": win_start.isoformat(), "as_of": as_of.isoformat()},
    )
    holidays = {r["day"] for r in query("SELECT day FROM holiday")}

    counts = {k: 0 for k in range(7)}
    for r in rows:
        counts[date.fromisoformat(r["day"]).weekday()] += 1
    weekday_avg = {k: v / (WINDOW_DAYS // 7) for k, v in counts.items()}

    expected_contracts = 0.0
    d = as_of + timedelta(days=1)
    while d <= end:
        expected_contracts += weekday_avg[d.weekday()] * (HOLIDAY_FACTOR if d.isoformat() in holidays else 1.0)
        d += timedelta(days=1)

    avg_amount = sum(r["amount"] for r in rows) / len(rows) if rows else 0.0
    ratios = [min(1.0, max(0.0, r["paid_same_day"] / r["amount"])) for r in rows]
    pay_ratio = sum(ratios) / len(ratios) if ratios else FALLBACK_PAY_RATIO
    value = expected_contracts * avg_amount * pay_ratio
    return {
        "expected_contracts": round(expected_contracts, 1),
        "avg_amount": int(round(avg_amount)),
        "pay_ratio": round(pay_ratio, 3),
        "pay_ratio_fallback": not ratios,
        "weekday_avg": [round(weekday_avg[k], 2) for k in range(7)],
        "value": int(round(value)),
    }


def achievement_color(rate: float) -> str:
    return "green" if rate >= 100 else "orange" if rate >= 95 else "red"


def revenue(as_of: date) -> dict:
    start, end = _month_bounds(as_of)
    i_conf = confirmed(start, as_of)
    r_sched = scheduled(start, as_of, end)
    n_new = new_inflow(as_of, end)
    forecast = i_conf["total"] + r_sched["expected"] + n_new["value"]
    target = query_one("SELECT target FROM monthly_target WHERE month = :m", {"m": start.strftime("%Y-%m")}).get("target")
    rate = round(forecast / target * 100, 1) if target else None
    return {
        "as_of": as_of.isoformat(),
        "month": start.strftime("%Y-%m"),
        "elapsed_days": (as_of - start).days + 1,
        "total_days": (end - start).days + 1,
        "confirmed": i_conf,
        "scheduled": r_sched,
        "new_inflow": n_new,
        "forecast": forecast,
        "target": target,
        "achievement": rate,
        "color": achievement_color(rate) if rate is not None else None,
        "formula": f"{n_new['expected_contracts']}건 × 평균 약정금 {n_new['avg_amount']:,}원 × 지급률 {n_new['pay_ratio']:.0%}",
    }


def monthly_actuals(as_of: date, months: int = 6) -> list[dict]:
    """지난 달들의 실제 확정 입금(같은 정의). 이번 달/지난달 토글과 비교 차트에 쓴다."""
    out = []
    cursor = as_of.replace(day=1)
    for _ in range(months):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        s, e = _month_bounds(cursor)
        out.append({"month": s.strftime("%Y-%m"), "confirmed": confirmed(s, e)["total"]})
    return list(reversed(out))


def backtest(as_of: date, months: int = 6, day: int = 15) -> dict:
    """지난 달들의 15일 시점으로 돌아가 예측하고, 그 달의 실제 확정 입금과 비교한다."""
    rows, cursor = [], as_of.replace(day=1)
    for _ in range(months):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        s, e = _month_bounds(cursor)
        mid = cursor.replace(day=min(day, e.day))
        predicted = revenue(mid)["forecast"]
        actual = confirmed(s, e)["total"]
        rows.append({"month": s.strftime("%Y-%m"), "as_of": mid.isoformat(), "forecast": predicted,
                     "actual": actual, "error_pct": round((predicted - actual) / actual * 100, 1)})
    mape = sum(abs(r["error_pct"]) for r in rows) / len(rows)
    return {"months": list(reversed(rows)), "mape": round(mape, 1)}
