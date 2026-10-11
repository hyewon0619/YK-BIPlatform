"""④ 경영 모니터링 — 지표가 "평소"와 다른 날을 찾아 상위 3개만 먼저 띄운다.

비교 기준(평소)
  일간  같은 요일 직전 12주     요일 효과가 커서 같은 요일끼리만 비교한다
  주간  직전 12개 ISO 주
  월간  직전 3개월
주간·월간은 마지막으로 끝난 주·월을 본다. 진행 중인 기간을 꽉 찬 기간과 비교하면 늘 떨어져 보인다.

이상 탐지 점수
  z = |x − μ| / σ
  Δ = |x − μ| (비율 지표, %p)  또는  |x − μ| / μ × 100 (건수·금액, %)
  score = max(z / 1.5, Δ / θ),  θ = 30 (%) 또는 10 (%p),  score ≥ 1 이면 후보

z 만 쓰지 않는 이유: 변화율만으로 줄 세우면 원래 출렁이는 지표가 늘 1등이 되고, z 만 쓰면 출렁이는
지표가 30~40% 빠져도 안 뜬다. 두 기준을 각자 문턱으로 정규화해 같은 무게로 비교한다.
기준 대비 10% 미만 변화는 특이점으로 보지 않는다. 매일 알림이 뜨면 아무도 보지 않으므로 최대 3개만 띄운다.
건 하나에 금액이 몰리는 성공보수 계열 금액은 매일 문턱을 넘어 상위 칸을 독차지하므로 후보에서 뺐다.
"""

from __future__ import annotations

import calendar
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from ..cache import SNAPSHOT_TTL, ttl_cache
from ..db import query, scattered_dates

LOW_AMOUNT = 1_000_000
DAILY_WEEKS = 12
WEEKLY_WEEKS = 12
MONTHLY_MONTHS = 3
Z_THRESHOLD = 1.5
THETA_PCT = 30.0
THETA_PP = 10.0
MIN_RELATIVE = 10.0
TOP_N = 3


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    kind: str  # count | amount | rate


METRICS = (
    Metric("calls", "콜 인입", "count"),
    Metric("reservations", "예약", "count"),
    Metric("visits", "방문", "count"),
    Metric("contracts", "선임", "count"),
    Metric("contract_rate", "선임률", "rate"),
    Metric("revenue", "약정금 합계", "amount"),
    Metric("value_per_contract", "부가가치(건당 약정금)", "amount"),
)
BY_KEY = {m.key: m for m in METRICS}


# ── 기간 ─────────────────────────────────────────────────────────────

def _month_range(y: int, m: int) -> tuple[date, date]:
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def periods(target: date, grain: str) -> tuple[tuple[date, date], list[tuple[date, date]]]:
    """(이번 기간, 기준 기간 목록). 기간은 [시작, 끝] 날짜 쌍이다."""
    if grain == "daily":
        return (target, target), [(target - timedelta(weeks=i),) * 2 for i in range(1, DAILY_WEEKS + 1)]
    if grain == "weekly":
        end = target if target.weekday() == 6 else target - timedelta(days=target.weekday() + 1)
        cur = (end - timedelta(days=6), end)
        return cur, [(cur[0] - timedelta(weeks=i), cur[1] - timedelta(weeks=i)) for i in range(1, WEEKLY_WEEKS + 1)]
    if grain == "monthly":
        last = target if target.day == calendar.monthrange(target.year, target.month)[1] else target.replace(day=1) - timedelta(days=1)
        cur = _month_range(last.year, last.month)
        base, cursor = [], cur[0]
        for _ in range(MONTHLY_MONTHS):
            cursor = (cursor - timedelta(days=1)).replace(day=1)
            base.append(_month_range(cursor.year, cursor.month))
        return cur, base
    raise ValueError(f"지원하지 않는 단위입니다: {grain}")


# ── 스냅샷: SELECT 한 번, 메모리에서 센다 ─────────────────────────────

SNAPSHOT_COLUMNS = """
    c.id, c.call_date, c.reserved_date, c.visit_date, c.contract_date, c.contract_amount, c.retain_type,
    c.consult_type, ch.name AS channel, b.name AS branch, t.major AS case_major, t.minor AS case_minor,
    l.name AS lawyer
"""
SNAPSHOT_JOINS = """
    FROM consultation c
    JOIN channel ch ON ch.id = c.channel_id JOIN branch b ON b.id = c.branch_id
    JOIN case_type t ON t.id = c.case_type_id JOIN lawyer l ON l.id = c.lawyer_id
"""


@ttl_cache(SNAPSHOT_TTL)
def snapshot_rows(ranges: tuple[tuple[date, date], ...]) -> tuple[dict, ...]:
    """여러 기간에 걸친 콜·예약·방문·선임 행을 한 번에 가져온다.

    지표마다 따로 원본을 읽으면, 라이브 원본에서는 조회 도중 들어온 신규 건이 어떤 지표에만 잡혀
    같은 날 숫자가 조회마다 1건씩 달라진다. 한 번만 읽고 그 스냅샷에서 모든 지표를 센다.
    """
    single_days = all(s == e for s, e in ranges)
    conds, params = [], {}
    for i, col in enumerate(("c.call_date", "c.reserved_date", "c.visit_date", "c.contract_date")):
        if single_days:
            sql, p = scattered_dates(col, [s for s, _ in ranges], prefix=f"d{i}_")
        else:
            lo, hi = min(s for s, _ in ranges), max(e for _, e in ranges)
            sql, p = f"({col} BETWEEN :lo{i} AND :hi{i})", {f"lo{i}": lo.isoformat(), f"hi{i}": hi.isoformat()}
        conds.append(sql)
        params.update(p)
    rows = query(f"SELECT {SNAPSHOT_COLUMNS} {SNAPSHOT_JOINS} WHERE {' OR '.join(conds)}", params)
    for r in rows:
        r["amount_bucket"] = amount_bucket(r["contract_amount"])
    return tuple(rows)


def amount_bucket(amount: int) -> str:
    for upper, label in ((1_000_000, "100만 미만"), (3_000_000, "100~300만"), (5_000_000, "300~500만"),
                         (10_000_000, "500~1000만")):
        if amount < upper:
            return label
    return "1000만 이상"


def excluded(row: dict) -> bool:
    """자문·저액 선임 제외 토글의 대상."""
    return row["retain_type"] == "자문" or (row["contract_date"] is not None and row["contract_amount"] < LOW_AMOUNT)


def _in(day: str | None, rng: tuple[date, date]) -> bool:
    return day is not None and rng[0].isoformat() <= day <= rng[1].isoformat()


def counts(rows, rng: tuple[date, date], exclude: bool = False) -> dict:
    """한 기간의 원천 값. 각 단계는 자기 날짜축으로 센다."""
    calls = sum(1 for r in rows if _in(r["call_date"], rng))
    reservations = sum(1 for r in rows if _in(r["reserved_date"], rng))
    visits = sum(1 for r in rows if _in(r["visit_date"], rng))
    contracted = [r for r in rows if _in(r["contract_date"], rng) and not (exclude and excluded(r))]
    return {"calls": calls, "reservations": reservations, "visits": visits,
            "contracts": len(contracted), "revenue": sum(r["contract_amount"] for r in contracted)}


def metric_values(c: dict) -> dict:
    return {
        **{k: c[k] for k in ("calls", "reservations", "visits", "contracts", "revenue")},
        "contract_rate": round(c["contracts"] / c["visits"] * 100, 2) if c["visits"] else 0.0,
        "value_per_contract": round(c["revenue"] / c["contracts"]) if c["contracts"] else 0,
    }


# ── 이상 탐지 ────────────────────────────────────────────────────────

def score(metric: Metric, x: float, history: list[float]) -> dict:
    mu = statistics.fmean(history) if history else 0.0
    sigma = statistics.pstdev(history) if len(history) > 1 else 0.0
    z = abs(x - mu) / sigma if sigma else 0.0
    if metric.kind == "rate":
        delta, theta = abs(x - mu), THETA_PP
    else:
        delta, theta = (abs(x - mu) / mu * 100 if mu else 0.0), THETA_PCT
    relative = abs(x - mu) / mu * 100 if mu else 0.0
    s = max(z / Z_THRESHOLD, delta / theta)
    return {
        "metric": metric.key, "label": metric.label, "kind": metric.kind,
        "value": x, "baseline_mean": round(mu, 2), "z": round(z, 2), "delta": round(delta, 1),
        "unit": "%p" if metric.kind == "rate" else "%", "direction": "상승" if x > mu else "하락",
        "score": round(s, 2), "candidate": s >= 1 and relative >= MIN_RELATIVE,
    }


def highlights(target: date, grain: str = "daily", exclude: bool = False) -> dict:
    cur, base = periods(target, grain)
    rows = snapshot_rows((cur, *base))
    now = metric_values(counts(rows, cur, exclude))
    hist = [metric_values(counts(rows, b, exclude)) for b in base]
    scored = [score(m, now[m.key], [h[m.key] for h in hist]) for m in METRICS]
    top = sorted((s for s in scored if s["candidate"]), key=lambda s: -s["score"])[:TOP_N]
    return {
        "grain": grain, "period": [cur[0].isoformat(), cur[1].isoformat()],
        "baseline_periods": len(base), "official": not exclude,
        "values": now, "highlights": top, "all": scored,
    }
