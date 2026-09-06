"""SQLite 커넥션 헬퍼.

BI 성격상 쓰기가 없어서 read-only 로 연다. 조회 로직은 전부 raw SQL 로
쓴다 — 지표 정의가 SQL 에 그대로 드러나야 나중에 검산하기 쉽다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "bi.db"


def get_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise RuntimeError(
            f"DB 가 없습니다: {DB_PATH}\n"
            "먼저 `python backend/scripts/generate_data.py` 를 실행하세요."
        )
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(sql, params or {}).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = query(sql, params)
    return rows[0] if rows else {}
