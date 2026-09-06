"""합성 상담 데이터 생성기.

실제 데이터는 한 건도 쓰지 않는다. 콜 -> 예약 -> 방문 -> 계약 퍼널을
확률 모델로 만들어 SQLite 에 적재한다. 시드를 고정해서 누가 돌려도
같은 데이터가 나온다.

데이터에 일부러 넣은 신호:
  - 요일 효과      월/화 콜이 많고 주말은 급감
  - 연간 계절성    3월·9월 성수기, 1월·8월 비수기
  - 완만한 성장    2년에 걸쳐 콜 물량 우상향
  - 지점 편차      지점마다 전환율/객단가가 다르다
  - 이상 구간      특정 날짜에 콜 급감 / 예약 전환 급락을 심어둠
                   (이상 탐지 기능이 이걸 잡아내는지 확인용)

실행:
    python backend/scripts/generate_data.py
"""

from __future__ import annotations

import math
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np

SEED = 20260906
DB_PATH = Path(__file__).resolve().parents[1] / "data" / "bi.db"

START_DATE = date(2024, 1, 1)
END_DATE = date(2025, 12, 31)

#: (지점명, 권역, 콜 물량 가중치, 전환력 보정, 객단가 배수)
BRANCHES = [
    ("강남",   "수도권", 1.00,  0.06, 1.35),
    ("서초",   "수도권", 0.82,  0.04, 1.28),
    ("송파",   "수도권", 0.61,  0.01, 1.10),
    ("일산",   "수도권", 0.44, -0.02, 0.95),
    ("수원",   "수도권", 0.58,  0.00, 1.02),
    ("인천",   "수도권", 0.49, -0.03, 0.92),
    ("대전",   "충청",   0.41, -0.01, 0.90),
    ("천안",   "충청",   0.27, -0.04, 0.84),
    ("대구",   "영남",   0.46,  0.01, 0.96),
    ("부산",   "영남",   0.63,  0.03, 1.08),
    ("울산",   "영남",   0.24, -0.05, 0.88),
    ("광주",   "호남",   0.38, -0.01, 0.93),
]

#: (유입 채널, 비중, 예약 전환 보정, 객단가 배수)
CHANNELS = [
    ("검색광고",   0.34,  0.02, 1.00),
    ("자연검색",   0.21,  0.05, 1.06),
    ("소셜",       0.14, -0.04, 0.88),
    ("지인소개",   0.12,  0.14, 1.22),
    ("재방문",     0.09,  0.18, 1.30),
    ("제휴",       0.06,  0.01, 1.04),
    ("기타",       0.04, -0.06, 0.85),
]

#: (상담 유형, 비중, 계약 전환 보정, 기준 계약금액(만원))
CATEGORIES = [
    ("일반상담",   0.31,  0.00,  320),
    ("정기관리",   0.19,  0.08,  180),
    ("분쟁조정",   0.16, -0.05,  760),
    ("자산관리",   0.13,  0.03, 1150),
    ("기업자문",   0.09,  0.06, 1680),
    ("기타",       0.12, -0.03,  260),
]

CANCEL_REASONS = [
    ("비용부담",       0.31),
    ("단순문의",       0.24),
    ("타사선택",       0.16),
    ("일정불가",       0.12),
    ("연락두절",       0.10),
    ("내부반려",       0.07),
]

#: 이상 탐지가 잡아내야 할 구간. (시작일, 일수, 콜 배수, 예약전환 배수, 메모)
ANOMALY_WINDOWS = [
    (date(2024, 5, 13), 3, 0.42, 1.00, "광고 계정 중단으로 콜 급감"),
    (date(2024, 9, 23), 2, 1.00, 0.48, "예약 시스템 장애로 예약 전환 급락"),
    (date(2025, 2, 10), 4, 0.55, 0.80, "설 연휴 직후 유입 감소"),
    (date(2025, 7, 7),  3, 1.85, 0.72, "바이럴 유입 폭증 · 응대 지연"),
    (date(2025, 11, 17), 3, 1.00, 0.55, "상담 인력 이탈로 예약 전환 하락"),
]


def _weekday_factor(d: date) -> float:
    """월~일 콜 물량 계수. 주말은 크게 떨어진다."""
    return [1.18, 1.12, 1.05, 1.02, 0.94, 0.42, 0.28][d.weekday()]


def _season_factor(d: date) -> float:
    """3월·9월 피크, 1월·8월 저점의 연간 주기."""
    day_of_year = d.timetuple().tm_yday
    return 1.0 + 0.17 * math.sin(2 * math.pi * (day_of_year - 50) / 365.0)


def _trend_factor(d: date) -> float:
    """관측 구간에 걸쳐 약 18% 성장."""
    elapsed = (d - START_DATE).days
    total = (END_DATE - START_DATE).days
    return 1.0 + 0.18 * (elapsed / total)


def _anomaly_factors(d: date) -> tuple[float, float]:
    for start, span, call_mult, reserve_mult, _memo in ANOMALY_WINDOWS:
        if start <= d < start + timedelta(days=span):
            return call_mult, reserve_mult
    return 1.0, 1.0


def _pick(rng: np.random.Generator, rows: list[tuple], weight_idx: int) -> int:
    weights = np.array([r[weight_idx] for r in rows], dtype=float)
    return int(rng.choice(len(rows), p=weights / weights.sum()))


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS consultation;
        DROP TABLE IF EXISTS branch;
        DROP TABLE IF EXISTS channel;
        DROP TABLE IF EXISTS category;

        CREATE TABLE branch (
            id     INTEGER PRIMARY KEY,
            name   TEXT NOT NULL,
            region TEXT NOT NULL
        );
        CREATE TABLE channel (
            id   INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE category (
            id   INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );

        -- 상담 1건 = 1행. 퍼널 단계는 날짜 컬럼이 채워졌는지로 판단한다.
        CREATE TABLE consultation (
            id              INTEGER PRIMARY KEY,
            branch_id       INTEGER NOT NULL REFERENCES branch(id),
            channel_id      INTEGER NOT NULL REFERENCES channel(id),
            category_id     INTEGER NOT NULL REFERENCES category(id),
            call_date       TEXT NOT NULL,   -- 콜 인입일 (항상 존재)
            reserved_date   TEXT,            -- 방문 예약 확정일
            visit_date      TEXT,            -- 실제 방문일
            contract_date   TEXT,            -- 계약 체결일
            cancel_reason   TEXT,            -- 이탈 사유 (계약 성사 시 NULL)
            contract_amount INTEGER NOT NULL DEFAULT 0,  -- 계약금액(원)
            success_fee     INTEGER NOT NULL DEFAULT 0   -- 성과보수(원)
        );

        CREATE INDEX idx_consultation_call    ON consultation(call_date);
        CREATE INDEX idx_consultation_visit   ON consultation(visit_date);
        CREATE INDEX idx_consultation_control ON consultation(contract_date);
        CREATE INDEX idx_consultation_branch  ON consultation(branch_id, call_date);
        """
    )


def generate() -> None:
    rng = np.random.default_rng(SEED)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    _create_schema(conn)

    conn.executemany(
        "INSERT INTO branch (id, name, region) VALUES (?, ?, ?)",
        [(i + 1, b[0], b[1]) for i, b in enumerate(BRANCHES)],
    )
    conn.executemany(
        "INSERT INTO channel (id, name) VALUES (?, ?)",
        [(i + 1, c[0]) for i, c in enumerate(CHANNELS)],
    )
    conn.executemany(
        "INSERT INTO category (id, name) VALUES (?, ?)",
        [(i + 1, c[0]) for i, c in enumerate(CATEGORIES)],
    )

    branch_weights = np.array([b[2] for b in BRANCHES], dtype=float)
    branch_weights /= branch_weights.sum()

    rows: list[tuple] = []
    next_id = 1
    current = START_DATE

    while current <= END_DATE:
        call_mult, reserve_mult = _anomaly_factors(current)
        expected = (
            96.0
            * _weekday_factor(current)
            * _season_factor(current)
            * _trend_factor(current)
            * call_mult
        )
        call_count = int(rng.poisson(max(expected, 1.0)))

        for _ in range(call_count):
            b_idx = int(rng.choice(len(BRANCHES), p=branch_weights))
            c_idx = _pick(rng, CHANNELS, 1)
            g_idx = _pick(rng, CATEGORIES, 1)

            _bname, _region, _w, branch_lift, price_mult = BRANCHES[b_idx]
            _cname, _cw, channel_lift, channel_price = CHANNELS[c_idx]
            _gname, _gw, category_lift, base_price = CATEGORIES[g_idx]

            call_date = current
            reserved_date = visit_date = contract_date = None
            cancel_reason = None
            contract_amount = success_fee = 0

            # 1단계: 콜 -> 예약
            p_reserve = np.clip(0.47 + branch_lift + channel_lift, 0.05, 0.95) * reserve_mult
            if rng.random() < p_reserve:
                reserved_date = call_date + timedelta(days=int(rng.integers(0, 6)))

                # 2단계: 예약 -> 방문 (노쇼가 존재)
                p_visit = np.clip(0.71 + branch_lift * 0.5, 0.05, 0.97)
                if rng.random() < p_visit:
                    visit_date = reserved_date + timedelta(days=int(rng.integers(0, 4)))

                    # 3단계: 방문 -> 계약
                    p_contract = np.clip(
                        0.52 + branch_lift + category_lift + channel_lift * 0.4, 0.05, 0.95
                    )
                    if rng.random() < p_contract:
                        contract_date = visit_date + timedelta(days=int(rng.integers(0, 9)))
                        amount = (
                            base_price
                            * 10_000
                            * price_mult
                            * channel_price
                            * float(rng.lognormal(0.0, 0.34))
                        )
                        contract_amount = int(round(amount / 10_000) * 10_000)
                        # 성과보수는 일부 계약에만 붙고, 계약금 대비 비율로 매긴다.
                        if rng.random() < 0.38:
                            success_fee = int(
                                round(contract_amount * float(rng.uniform(0.08, 0.31)) / 10_000)
                                * 10_000
                            )

            if contract_date is None:
                r_idx = _pick(rng, CANCEL_REASONS, 1)
                cancel_reason = CANCEL_REASONS[r_idx][0]

            rows.append(
                (
                    next_id,
                    b_idx + 1,
                    c_idx + 1,
                    g_idx + 1,
                    call_date.isoformat(),
                    reserved_date.isoformat() if reserved_date else None,
                    visit_date.isoformat() if visit_date else None,
                    contract_date.isoformat() if contract_date else None,
                    cancel_reason,
                    contract_amount,
                    success_fee,
                )
            )
            next_id += 1

        current += timedelta(days=1)

    conn.executemany(
        """INSERT INTO consultation
           (id, branch_id, channel_id, category_id, call_date, reserved_date,
            visit_date, contract_date, cancel_reason, contract_amount, success_fee)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()

    total = len(rows)
    contracts = sum(1 for r in rows if r[7])
    revenue = sum(r[9] for r in rows)
    print(f"DB 생성 완료: {DB_PATH}")
    print(f"  상담 {total:,}건 / 계약 {contracts:,}건 (계약률 {contracts / total:.1%})")
    print(f"  총 계약금액 {revenue:,}원")
    print(f"  기간 {START_DATE} ~ {END_DATE}")
    print(f"  심어둔 이상 구간 {len(ANOMALY_WINDOWS)}개")
    conn.close()


if __name__ == "__main__":
    generate()
