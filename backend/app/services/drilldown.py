"""차원별 드릴다운 — 지점 / 권역 / 채널 / 상담유형 / 이탈사유.

퍼널 숫자가 떨어졌을 때 "어디가 떨어졌는지"를 한 번에 보기 위한 것.
차원 이름은 화이트리스트로만 받는다 (사용자 입력을 SQL 에 넣지 않는다).
"""

from __future__ import annotations

from datetime import date

from ..db import query

#: 허용 차원 -> (조인/컬럼식, 표시 라벨)
DIMENSIONS: dict[str, tuple[str, str]] = {
    "branch": ("b.name", "지점"),
    "region": ("b.region", "권역"),
    "channel": ("ch.name", "유입 채널"),
    "category": ("cat.name", "상담 유형"),
}


def by_dimension(dimension: str, start: date, end: date) -> dict:
    if dimension not in DIMENSIONS:
        raise ValueError(
            f"지원하지 않는 차원입니다: {dimension} (가능: {', '.join(DIMENSIONS)})"
        )
    column, label = DIMENSIONS[dimension]

    rows = query(
        f"""
        SELECT
            {column}                                            AS name,
            COUNT(*)                                            AS calls,
            SUM(CASE WHEN c.reserved_date IS NOT NULL THEN 1 END) AS reservations,
            SUM(CASE WHEN c.visit_date    IS NOT NULL THEN 1 END) AS visits,
            SUM(CASE WHEN c.contract_date IS NOT NULL THEN 1 END) AS contracts,
            COALESCE(SUM(c.contract_amount), 0)                 AS revenue
        FROM consultation c
        JOIN branch   b   ON b.id   = c.branch_id
        JOIN channel  ch  ON ch.id  = c.channel_id
        JOIN category cat ON cat.id = c.category_id
        WHERE c.call_date BETWEEN :start AND :end
        GROUP BY {column}
        ORDER BY revenue DESC
        """,
        {"start": start.isoformat(), "end": end.isoformat()},
    )

    total_revenue = sum(r["revenue"] for r in rows) or 1
    for r in rows:
        calls = r["calls"] or 0
        contracts = r["contracts"] or 0
        r["reservations"] = r["reservations"] or 0
        r["visits"] = r["visits"] or 0
        r["contracts"] = contracts
        r["overall_rate"] = round(contracts / calls * 100, 1) if calls else 0.0
        r["revenue_share"] = round(r["revenue"] / total_revenue * 100, 1)
        r["revenue_per_call"] = int(r["revenue"] / calls) if calls else 0

    return {
        "dimension": dimension,
        "label": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rows": rows,
    }


def cancel_reasons(start: date, end: date) -> dict:
    """이탈 사유 분포 — 어느 단계에서 빠졌는지까지 같이 본다."""
    rows = query(
        """
        SELECT
            cancel_reason AS name,
            COUNT(*)      AS total,
            SUM(CASE WHEN reserved_date IS NULL THEN 1 END)                          AS dropped_at_call,
            SUM(CASE WHEN reserved_date IS NOT NULL AND visit_date IS NULL THEN 1 END) AS dropped_at_reservation,
            SUM(CASE WHEN visit_date IS NOT NULL THEN 1 END)                         AS dropped_at_visit
        FROM consultation
        WHERE call_date BETWEEN :start AND :end
          AND cancel_reason IS NOT NULL
        GROUP BY cancel_reason
        ORDER BY total DESC
        """,
        {"start": start.isoformat(), "end": end.isoformat()},
    )
    total = sum(r["total"] for r in rows) or 1
    for r in rows:
        for key in ("dropped_at_call", "dropped_at_reservation", "dropped_at_visit"):
            r[key] = r[key] or 0
        r["share"] = round(r["total"] / total * 100, 1)
    return {"start": start.isoformat(), "end": end.isoformat(), "total": total, "rows": rows}
