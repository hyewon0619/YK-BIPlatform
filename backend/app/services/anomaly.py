"""일자별 이상 탐지.

요일 효과가 지배적이라 "전일 대비"로는 아무것도 못 잡는다. 그래서
**같은 요일의 과거 N주**를 기준 분포로 삼고, 그 분포에서 얼마나 벗어났는지
robust z-score 로 본다.

평균/표준편차 대신 중앙값/MAD 를 쓰는 이유: 기준 구간 안에 이상치가
섞여 있으면 평균과 표준편차가 같이 끌려가서 정작 그 이상치를 못 잡는다.
MAD 는 그 영향을 훨씬 덜 받는다.

    robust_z = 0.6745 * (x - median) / MAD
"""

from __future__ import annotations

from datetime import date, timedelta

from ..db import query_one
from .funnel import snapshot

#: |robust z| 가 이 값을 넘으면 1차 후보로 본다.
Z_THRESHOLD = 3.5
#: 기준 분포로 삼을 과거 같은 요일 개수.
LOOKBACK_WEEKS = 12
#: 감시할 지표.
WATCHED = ("calls", "reservations", "contracts", "reservation_rate", "overall_rate")

#: z-score 만으로는 부족하다. 토요일 계약 건수처럼 값 자체가 작은 지표는
#: 한두 건만 흔들려도 MAD 가 작아 z 가 쉽게 튄다. 그래서 두 가지를 더 건다.
#:   1) 기준 중앙값 대비 상대 편차가 이 비율 이상일 것
#:   2) 기준 중앙값이 이 수준 이상일 것 (표본이 너무 작으면 판단 보류)
MIN_RELATIVE_DEVIATION = 0.25

#: 지표 하나만 튀는 건 대개 노이즈다. 실제 사고는 여러 지표를 같이 흔든다.
#: (예: 예약 시스템 장애 -> 예약수·예약률·최종전환율이 동시에 떨어진다)
#: 이 값 이상의 지표가 동시에 걸려야 그 날을 이상으로 판정한다.
MIN_FLAGGED_METRICS = 2

MIN_BASELINE = {
    "calls": 20.0,
    "reservations": 10.0,
    "contracts": 8.0,
    "reservation_rate": 10.0,
    "overall_rate": 5.0,
}


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _robust_z(current: float, history: list[float]) -> tuple[float, float, float]:
    """(z, median, mad) 를 돌려준다."""
    med = _median(history)
    mad = _median([abs(v - med) for v in history])
    if mad == 0:
        # 과거가 전부 같은 값이면 MAD 가 0 이 된다. 평균 편차로 대체한다.
        spread = sum(abs(v - med) for v in history) / len(history) if history else 0.0
        if spread == 0:
            return 0.0, med, 0.0
        return (current - med) / spread, med, spread
    return 0.6745 * (current - med) / mad, med, mad


def detect(
    target: date,
    weeks: int = LOOKBACK_WEEKS,
    threshold: float = Z_THRESHOLD,
    min_metrics: int = MIN_FLAGGED_METRICS,
) -> dict:
    current = snapshot(target)
    history = [snapshot(target - timedelta(weeks=i)) for i in range(1, weeks + 1)]

    findings = []
    for metric in WATCHED:
        past = [h[metric] for h in history]
        z, med, spread = _robust_z(current[metric], past)

        relative = abs(current[metric] - med) / med if med else 0.0
        flagged = (
            abs(z) >= threshold
            and relative >= MIN_RELATIVE_DEVIATION
            and med >= MIN_BASELINE.get(metric, 0.0)
        )

        findings.append(
            {
                "metric": metric,
                "value": current[metric],
                "baseline_median": round(med, 2),
                "spread": round(spread, 2),
                "robust_z": round(z, 2),
                "relative_deviation": round(relative * 100, 1),
                "direction": "급증" if z > 0 else "급감",
                "flagged": flagged,
            }
        )

    flagged_count = sum(1 for f in findings if f["flagged"])

    return {
        "date": target.isoformat(),
        "weekday": ["월", "화", "수", "목", "금", "토", "일"][target.weekday()],
        "lookback_weeks": weeks,
        "threshold": threshold,
        "min_metrics": min_metrics,
        "flagged_count": flagged_count,
        "anomalous": flagged_count >= min_metrics,
        "findings": findings,
    }


def scan(
    start: date,
    end: date,
    threshold: float = Z_THRESHOLD,
    min_metrics: int = MIN_FLAGGED_METRICS,
) -> dict:
    """구간 전체를 훑어 이상 일자만 추린다."""
    days = (end - start).days
    hits = []
    for i in range(days + 1):
        day = start + timedelta(days=i)
        result = detect(day, threshold=threshold, min_metrics=min_metrics)
        if result["anomalous"]:
            hits.append(
                {
                    "date": result["date"],
                    "weekday": result["weekday"],
                    "metrics": [f for f in result["findings"] if f["flagged"]],
                }
            )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "scanned_days": days + 1,
        "anomaly_count": len(hits),
        "anomalies": hits,
    }
