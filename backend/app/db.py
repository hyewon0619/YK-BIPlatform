"""읽기 전용 원천 연결과 조회 헬퍼.

플랫폼은 운영 DB 를 직접 건드리지 않는다. 매일 복제되는 읽기 전용 사본을 화면 요청마다
바로 읽는다. 공개본에서는 SQLite 를 mode=ro 로 열어 같은 제약을 건다.
조회 로직은 raw SQL 로 쓴다. 지표 정의가 SQL 에 그대로 드러나야 나중에 검산하기 쉽다.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

DB_PATH = Path(os.getenv("BI_DB_PATH", Path(__file__).resolve().parents[1] / "data" / "bi.db"))


def get_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise RuntimeError(
            f"DB 가 없습니다: {DB_PATH}\n먼저 `python backend/scripts/generate_data.py` 를 실행하세요."
        )
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(sql, params or {}).fetchall()]
    finally:
        conn.close()


def query_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = query(sql, params)
    return rows[0] if rows else {}


def scattered_dates(column: str, days: Iterable[date], prefix: str = "d") -> tuple[str, dict[str, str]]:
    """같은 요일 12주처럼 띄엄띄엄한 날짜 집합 D 를 조회하는 조건을 만든다.

    결과를 바꾸지 않는 범위 조건(col ∈ [min D, max D + 1일))을 IN 옆에 덧붙여 인덱스를 탈 여지를 만든다.
    """
    ds = sorted(set(days))
    names = [f"{prefix}{i}" for i in range(len(ds))]
    params = {n: d.isoformat() for n, d in zip(names, ds)}
    params[f"{prefix}_lo"] = ds[0].isoformat()
    params[f"{prefix}_hi"] = (ds[-1] + timedelta(days=1)).isoformat()
    sql = (f"({column} >= :{prefix}_lo AND {column} < :{prefix}_hi "
           f"AND DATE({column}) IN ({', '.join(':' + n for n in names)}))")
    return sql, params
