"""합성 데이터 생성기.

실제 데이터는 한 건도 쓰지 않는다. 상담 기반 법률 서비스의 데이터 구조
(콜 → 예약 → 방문 → 선임, 분할 납부, 사건 묶음, 성공보수, 사례 콘텐츠)를
확률 모델로 만들어 SQLite 에 적재한다. 시드를 고정해서 누가 돌려도 같은 데이터가 나온다.

데이터에 일부러 넣은 신호:
  - 요일 효과      월/화 콜이 많고 주말은 급감
  - 연간 계절성    3월·9월 성수기, 1월·8월 비수기
  - 지점·변호사 편차
  - 이상 구간      특정 날짜에 콜 급감 / 선임 전환 급락 / 저액 일괄 등록
  - 사건 동시출현  이혼 → 재산분할·양육권, 형사 → 손해배상처럼 함께 선임되는 유형
  - 납부 행태      제때 / 1~10일 연체 / 장기 미납 회차가 섞인 분할 납부

실행:
    python backend/scripts/generate_data.py
"""

from __future__ import annotations

import math
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

SEED = 20260906
DB_PATH = Path(__file__).resolve().parents[1] / "data" / "bi.db"

START_DATE = date(2024, 10, 1)
END_DATE = date(2026, 9, 15)  # 월 중간에서 끝나야 "당월 예측"이 의미가 있다.

#: (지점명, 권역, 콜 물량 가중치, 전환력 보정)
BRANCHES = [
    ("강남", "수도권", 1.00, 0.06), ("서초", "수도권", 0.82, 0.04), ("수원", "수도권", 0.58, 0.00),
    ("인천", "수도권", 0.49, -0.03), ("대전", "충청", 0.41, -0.01), ("대구", "영남", 0.46, 0.01),
    ("부산", "영남", 0.63, 0.03), ("광주", "호남", 0.38, -0.01),
]

#: (유입 경로, 비중, 예약 전환 보정, 소개 사건 여부)
CHANNELS = [
    ("검색광고", 0.36, 0.02, False), ("자연검색", 0.20, 0.05, False), ("블로그", 0.12, -0.02, False),
    ("유튜브", 0.10, -0.04, False), ("재방문", 0.08, 0.15, False), ("소개", 0.14, 0.20, True),
]

#: (대분류, 소분류, 비중, 선임 전환 보정, 기준 약정금(만원), 성공보수 발생률)
CASE_TYPES = [
    ("형사", "사기", 0.10, 0.02, 550, 0.55), ("형사", "폭행", 0.07, 0.04, 380, 0.60),
    ("형사", "성범죄", 0.06, 0.08, 880, 0.50), ("형사", "교통사고", 0.06, 0.00, 330, 0.65),
    ("이혼", "협의이혼", 0.06, -0.04, 280, 0.40), ("이혼", "재판이혼", 0.09, 0.05, 660, 0.45),
    ("이혼", "재산분할", 0.05, 0.03, 720, 0.50), ("이혼", "양육권", 0.04, 0.01, 450, 0.45),
    ("민사", "손해배상", 0.10, -0.02, 420, 0.40), ("민사", "대여금", 0.07, -0.05, 300, 0.45),
    ("민사", "임대차", 0.07, -0.03, 320, 0.40), ("노동", "부당해고", 0.05, 0.01, 400, 0.45),
    ("노동", "임금체불", 0.05, -0.04, 260, 0.50), ("상속", "유류분", 0.07, 0.03, 760, 0.40),
    ("상속", "상속재산분할", 0.06, 0.02, 690, 0.40),
]

#: 함께 선임되는 경향. (본건 소분류, 동반 소분류, 확률)
CO_OCCUR = [
    ("재판이혼", "재산분할", 0.42), ("재판이혼", "양육권", 0.31), ("협의이혼", "재산분할", 0.18),
    ("재산분할", "양육권", 0.15), ("사기", "손해배상", 0.33), ("폭행", "손해배상", 0.38),
    ("성범죄", "손해배상", 0.12), ("교통사고", "손해배상", 0.45), ("부당해고", "임금체불", 0.35),
    ("유류분", "상속재산분할", 0.30), ("임대차", "손해배상", 0.10), ("대여금", "사기", 0.12),
]

CONSULT_TYPES = [("전화", 0.45, -0.04), ("방문", 0.40, 0.06), ("화상", 0.15, 0.00)]
#: (선임형태, 비중) — 성공보수만 약정한 건은 약정금이 0 이다.
RETAIN_TYPES = [("착수금", 0.42), ("착수금+성공보수", 0.43), ("성공보수만", 0.07), ("자문", 0.08)]
CANCEL_REASONS = [("비용부담", 0.31), ("단순문의", 0.24), ("타사선택", 0.16), ("일정불가", 0.12),
                  ("연락두절", 0.10), ("내부반려", 0.07)]
#: 결제 상태. 정상이 아닌 상태는 매출 예측에서 뺀다.
PAY_STATUSES = [("정상", 0.92), ("사임미반환", 0.02), ("불확정", 0.02), ("불성립", 0.01),
                ("조건부", 0.02), ("지급명령", 0.01)]
#: 종결 형태. 사임·소취하·합의는 성공보수가 생길 수 없는 종결이다.
CLOSE_TYPES = [("판결", 0.46), ("불기소·무혐의", 0.12), ("조정", 0.14), ("사임", 0.10),
               ("소취하", 0.08), ("합의", 0.10)]

#: (시작일, 일수, 콜 배수, 선임 전환 배수, 저액 일괄 등록 건수, 메모)
ANOMALY_WINDOWS = [
    (date(2025, 3, 10), 3, 0.42, 1.00, 0, "광고 계정 중단으로 콜 급감"),
    (date(2025, 6, 23), 2, 1.00, 0.45, 0, "상담 예약 시스템 장애로 선임 전환 급락"),
    (date(2025, 9, 8), 3, 1.80, 0.80, 0, "바이럴 유입 폭증 · 응대 지연"),
    (date(2026, 4, 14), 1, 1.00, 1.00, 14, "성공보수만 약정한 건이 한 담당자로 일괄 등록"),
    (date(2026, 8, 18), 3, 1.00, 0.55, 0, "상담 인력 이탈로 선임 전환 하락"),
]

HOLIDAYS = [
    "2024-10-03", "2024-10-09", "2024-12-25", "2025-01-01", "2025-01-28", "2025-01-29", "2025-01-30",
    "2025-03-03", "2025-05-05", "2025-05-06", "2025-06-06", "2025-08-15", "2025-10-03", "2025-10-06",
    "2025-10-07", "2025-10-08", "2025-10-09", "2025-12-25", "2026-01-01", "2026-02-16", "2026-02-17",
    "2026-02-18", "2026-03-02", "2026-05-05", "2026-05-25", "2026-06-03", "2026-08-17", "2026-09-24",
    "2026-09-25", "2026-09-26", "2026-10-05", "2026-10-09",
]

SUMMARY_TEMPLATES = {
    "사기": ["투자 권유를 받고 송금했는데 연락이 끊겼다", "중고거래 대금을 보냈으나 물건을 받지 못했다"],
    "폭행": ["술자리에서 시비가 붙어 폭행을 당해 전치 3주 진단을 받았다", "층간소음 다툼 중 밀쳐져 다쳤다"],
    "성범죄": ["직장 회식 자리에서 원치 않는 신체 접촉을 당했다", "온라인에서 불법 촬영물 유포 협박을 받았다"],
    "교통사고": ["신호 대기 중 후방 추돌로 입원 치료를 받았다", "보행 중 차량에 치여 보험사와 합의가 안 된다"],
    "협의이혼": ["배우자와 이혼에 합의했지만 위자료 조건을 정리하고 싶다", "협의이혼 숙려기간 중 재산 정리가 걱정된다"],
    "재판이혼": ["배우자의 외도로 이혼 소송을 원하고 재산과 아이 문제가 걱정된다", "장기간 별거 중이고 상대가 이혼을 거부한다"],
    "재산분할": ["혼인 중 마련한 아파트의 분할 비율을 다투고 있다", "배우자 명의 재산을 숨긴 정황이 있다"],
    "양육권": ["이혼 후 아이 양육권과 양육비를 받고 싶다", "면접교섭이 지켜지지 않는다"],
    "손해배상": ["사고로 입은 치료비와 위자료를 청구하고 싶다", "계약 위반으로 손해가 발생했다"],
    "대여금": ["지인에게 빌려준 돈을 돌려받지 못하고 있다", "차용증 없이 송금한 돈을 받고 싶다"],
    "임대차": ["계약이 끝났는데 보증금을 돌려받지 못하고 있다", "집주인이 수리를 거부한다"],
    "부당해고": ["갑자기 해고 통보를 받았는데 사유가 납득되지 않는다", "권고사직을 강요받았다"],
    "임금체불": ["퇴직 후 임금과 퇴직금을 받지 못했다", "수당이 몇 달째 지급되지 않는다"],
    "유류분": ["부모님이 형제에게만 재산을 증여했다", "유언으로 상속에서 배제되었다"],
    "상속재산분할": ["형제들과 상속 재산 분할 비율이 합의되지 않는다", "부동산 상속 지분 정리가 필요하다"],
}

LOW_AMOUNT = 1_000_000  # 저액 선임 기준(원)


def _weekday_factor(d: date) -> float:
    return [1.18, 1.12, 1.05, 1.02, 0.94, 0.42, 0.28][d.weekday()]


def _season_factor(d: date) -> float:
    return 1.0 + 0.17 * math.sin(2 * math.pi * (d.timetuple().tm_yday - 50) / 365.0)


def _anomaly(d: date) -> tuple[float, float, int]:
    for start, span, call_mult, contract_mult, low_bulk, _memo in ANOMALY_WINDOWS:
        if start <= d < start + timedelta(days=span):
            return call_mult, contract_mult, low_bulk
    return 1.0, 1.0, 0


def _workday(d: date) -> date:
    """사무소는 일요일에 방문·선임을 받지 않는다."""
    return d + timedelta(days=1) if d.weekday() == 6 else d


def _pick(rng, rows, idx=1) -> int:
    w = np.array([r[idx] for r in rows], dtype=float)
    return int(rng.choice(len(rows), p=w / w.sum()))


def _months_after(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, 28)
    return date(y, m, day)


SCHEMA = """
CREATE TABLE branch (id INTEGER PRIMARY KEY, name TEXT NOT NULL, region TEXT NOT NULL);
CREATE TABLE channel (id INTEGER PRIMARY KEY, name TEXT NOT NULL, is_referral INTEGER NOT NULL);
CREATE TABLE case_type (id INTEGER PRIMARY KEY, major TEXT NOT NULL, minor TEXT NOT NULL);
CREATE TABLE lawyer (id INTEGER PRIMARY KEY, name TEXT NOT NULL, branch_id INTEGER NOT NULL);

-- 상담 1건 = 1행. 퍼널 단계는 날짜 컬럼이 채워졌는지로 판단한다.
CREATE TABLE consultation (
    id              INTEGER PRIMARY KEY,
    branch_id       INTEGER NOT NULL REFERENCES branch(id),
    channel_id      INTEGER NOT NULL REFERENCES channel(id),
    case_type_id    INTEGER NOT NULL REFERENCES case_type(id),
    lawyer_id       INTEGER NOT NULL REFERENCES lawyer(id),
    consult_type    TEXT NOT NULL,
    referrer        TEXT,            -- 소개자. 있으면 오프라인 사건
    summary         TEXT NOT NULL,   -- 상담 요약 (추천 B 의 질의에 쓴다)
    call_date       TEXT NOT NULL,
    reserved_date   TEXT,
    visit_date      TEXT,
    contract_date   TEXT,            -- 선임일
    cancel_reason   TEXT,
    retain_type     TEXT,            -- 선임형태
    contract_amount INTEGER NOT NULL DEFAULT 0,   -- 약정금(원)
    sf_expected     INTEGER NOT NULL DEFAULT 0    -- 최대 예상 성공보수(원)
);

-- 수임(선임된 상담) 단위. 결제 상태·종결 정보를 가진다.
CREATE TABLE engagement (
    id            INTEGER PRIMARY KEY REFERENCES consultation(id),
    pay_status    TEXT NOT NULL,
    terminated    INTEGER NOT NULL DEFAULT 0,   -- 계약 해지
    closed_date   TEXT,
    close_type    TEXT,
    sf_occurred   INTEGER NOT NULL DEFAULT 0    -- 실제 발생한 성공보수(원)
);
-- 한 수임 안의 사건 목록. 동시출현 추천의 장바구니다.
CREATE TABLE engagement_case (
    engagement_id INTEGER NOT NULL REFERENCES engagement(id),
    case_type_id  INTEGER NOT NULL REFERENCES case_type(id),
    PRIMARY KEY (engagement_id, case_type_id)
);
-- 분할 납부 회차. seq 0 은 계약 당일 착수금이다.
CREATE TABLE installment (
    id            INTEGER PRIMARY KEY,
    engagement_id INTEGER NOT NULL REFERENCES engagement(id),
    seq           INTEGER NOT NULL,
    due_date      TEXT NOT NULL,
    amount        INTEGER NOT NULL,
    paid_date     TEXT             -- 실제 입금일. 없으면 미납
);
CREATE TABLE refund (
    id            INTEGER PRIMARY KEY,
    engagement_id INTEGER NOT NULL REFERENCES engagement(id),
    refund_date   TEXT NOT NULL,
    amount        INTEGER NOT NULL
);
-- 추천에 쓰는 사례·영상 콘텐츠.
CREATE TABLE content (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,      -- 사례 | 영상
    case_type_id INTEGER REFERENCES case_type(id),  -- 영상은 유형 메타데이터가 없다
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    is_public    INTEGER NOT NULL
);
CREATE TABLE holiday (day TEXT PRIMARY KEY);
CREATE TABLE monthly_target (month TEXT PRIMARY KEY, target INTEGER NOT NULL);

CREATE INDEX ix_c_call     ON consultation(call_date);
CREATE INDEX ix_c_visit    ON consultation(visit_date);
CREATE INDEX ix_c_contract ON consultation(contract_date);
CREATE INDEX ix_i_eng      ON installment(engagement_id);
CREATE INDEX ix_i_paid     ON installment(paid_date);
CREATE INDEX ix_i_due      ON installment(due_date);
"""


def _installments(rng, eng_id: int, contract: date, amount: int, retain_type: str):
    """약정금을 회차로 나누고 납부 행태를 입힌다. END_DATE 이후 입금은 기록하지 않는다."""
    rows = []
    if amount <= 0:
        return rows
    n_more = 0 if retain_type == "자문" else int(rng.choice([0, 1, 2, 3, 4], p=[0.30, 0.22, 0.22, 0.16, 0.10]))
    day0_ratio = 1.0 if n_more == 0 else float(rng.uniform(0.35, 0.8))
    day0 = int(round(amount * day0_ratio / 10_000) * 10_000)
    plan = [(0, contract, day0)]
    rest = amount - day0
    for k in range(1, n_more + 1):
        part = rest // n_more if k < n_more else rest - (rest // n_more) * (n_more - 1)
        plan.append((k, _months_after(contract, k), part))

    # 납부 성향: 대부분 제때 내고, 일부는 조금 늦고, 일부는 장기 미납으로 간다.
    habit = rng.choice(["ontime", "late", "stop"], p=[0.78, 0.14, 0.08])
    stopped = False
    for seq, due, amt in plan:
        if seq == 0:
            # 계약 당일 착수금은 대부분 바로 들어오지만, 일부는 며칠 뒤 들어온다.
            paid = due if rng.random() < 0.86 else due + timedelta(days=int(rng.integers(1, 6)))
        elif stopped or (habit == "stop" and rng.random() < 0.5):
            stopped = True
            paid = None
        elif habit == "late":
            paid = due + timedelta(days=int(rng.integers(1, 11)))
        else:
            paid = due if rng.random() < 0.9 else due + timedelta(days=int(rng.integers(1, 4)))
        if paid is not None and paid > END_DATE:
            paid = None
        rows.append((eng_id, seq, due.isoformat(), amt, paid.isoformat() if paid else None))
    return rows


def generate(path: Path = DB_PATH) -> Path:
    rng = np.random.default_rng(SEED)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    conn.executemany("INSERT INTO branch VALUES (?, ?, ?)", [(i + 1, b[0], b[1]) for i, b in enumerate(BRANCHES)])
    conn.executemany("INSERT INTO channel VALUES (?, ?, ?)", [(i + 1, c[0], int(c[3])) for i, c in enumerate(CHANNELS)])
    conn.executemany("INSERT INTO case_type VALUES (?, ?, ?)", [(i + 1, t[0], t[1]) for i, t in enumerate(CASE_TYPES)])
    surnames, given = "김이박최정강조윤장임한오서신", ["민준", "서연", "도윤", "하은", "준호", "지민", "현우", "수빈", "예린", "태윤"]
    lawyers = []
    for i in range(1, 41):
        lawyers.append((i, f"{surnames[i % len(surnames)]}{given[(i * 7) % len(given)]}", (i - 1) % len(BRANCHES) + 1))
    conn.executemany("INSERT INTO lawyer VALUES (?, ?, ?)", lawyers)
    lawyers_by_branch = {b: [l[0] for l in lawyers if l[2] == b] for b in range(1, len(BRANCHES) + 1)}
    # 변호사마다 전환력이 조금씩 다르다. 표본이 적은 변호사는 선임률이 0% 나 100% 로 튀기 쉽다.
    lawyer_lift = {l[0]: float(rng.normal(0, 0.06)) for l in lawyers}
    minor_index = {t[1]: i + 1 for i, t in enumerate(CASE_TYPES)}

    branch_w = np.array([b[2] for b in BRANCHES], dtype=float)
    branch_w /= branch_w.sum()

    consults, engagements, eng_cases, installments, refunds = [], [], [], [], []
    next_id = 1
    d = START_DATE
    while d <= END_DATE:
        call_mult, _contract_mult, low_bulk = _anomaly(d)
        expected = 92.0 * _weekday_factor(d) * _season_factor(d) * call_mult
        if d.isoformat() in HOLIDAYS:
            expected *= 0.35
        for _ in range(int(rng.poisson(max(expected, 1.0)))):
            b = int(rng.choice(len(BRANCHES), p=branch_w))
            ch = _pick(rng, CHANNELS)
            t = _pick(rng, CASE_TYPES, 2)
            ct = _pick(rng, CONSULT_TYPES)
            lawyer_id = int(rng.choice(lawyers_by_branch[b + 1]))
            major, minor, _w, type_lift, base_price, _sf = CASE_TYPES[t]
            referral = CHANNELS[ch][3]
            summary = str(rng.choice(SUMMARY_TEMPLATES[minor]))

            reserved = visit = contract = None
            cancel = retain = None
            amount = sf_expected = 0
            if rng.random() < np.clip(0.47 + BRANCHES[b][3] + CHANNELS[ch][2], 0.05, 0.95):
                reserved = d + timedelta(days=int(rng.integers(0, 5)))
                if rng.random() < np.clip(0.72 + BRANCHES[b][3] * 0.5, 0.05, 0.97):
                    visit = _workday(reserved + timedelta(days=int(rng.integers(0, 4))))
                    p = 0.50 + BRANCHES[b][3] + type_lift + CONSULT_TYPES[ct][2] + lawyer_lift[lawyer_id]
                    if referral:
                        p += 0.30  # 소개로 온 고객은 방문 시점에 이미 선임 의사가 있다.
                    # 선임 전환 이상은 방문한 날에 걸린다(상담 인력·예약 시스템 문제는 방문 당일에 드러난다).
                    if rng.random() < np.clip(p, 0.05, 0.98) * _anomaly(visit)[1]:
                        contract = _workday(visit + timedelta(days=int(rng.choice([0, 0, 0, 1, 2, 3]))))
                        retain = RETAIN_TYPES[_pick(rng, RETAIN_TYPES)][0]
                        price = base_price * 10_000 * float(rng.lognormal(0.0, 0.38))
                        if referral:
                            price *= float(rng.lognormal(0.5, 0.9))  # 소개 사건은 긴 꼬리
                        if retain == "자문":
                            price *= 0.35
                        amount = 0 if retain == "성공보수만" else int(round(price / 100_000) * 100_000)
                        if retain in ("착수금+성공보수", "성공보수만"):
                            sf_expected = int(round(price * float(rng.uniform(0.6, 1.4)) / 100_000) * 100_000)
            if contract is None:
                cancel = CANCEL_REASONS[_pick(rng, CANCEL_REASONS)][0]
            if contract and contract > END_DATE:
                contract, retain, amount, sf_expected = None, None, 0, 0
                cancel = "일정불가"

            cid = next_id
            next_id += 1
            consults.append((cid, b + 1, ch + 1, t + 1, lawyer_id, CONSULT_TYPES[ct][0],
                             f"소개자{int(rng.integers(1, 400))}" if referral else None, summary,
                             d.isoformat(), reserved.isoformat() if reserved else None,
                             visit.isoformat() if visit else None, contract.isoformat() if contract else None,
                             cancel, retain, amount, sf_expected))
            if not contract:
                continue

            pay_status = PAY_STATUSES[_pick(rng, PAY_STATUSES)][0]
            terminated = int(rng.random() < 0.02)
            closed = close_type = None
            sf_occurred = 0
            age = (END_DATE - contract).days
            if age > 60 and rng.random() < min(0.92, age / 420):
                closed = contract + timedelta(days=int(rng.integers(60, max(61, age))))
                close_type = CLOSE_TYPES[_pick(rng, CLOSE_TYPES)][0]
                if sf_expected and close_type not in ("사임", "소취하", "합의") and rng.random() < CASE_TYPES[t][5]:
                    sf_occurred = int(round(sf_expected * float(rng.uniform(0.3, 1.0)) / 100_000) * 100_000)
            engagements.append((cid, pay_status, terminated, closed.isoformat() if closed else None, close_type, sf_occurred))

            types = {t + 1}
            for main, extra, p in CO_OCCUR:
                if main == minor and rng.random() < p:
                    types.add(minor_index[extra])
            eng_cases += [(cid, tid) for tid in sorted(types)]
            installments += _installments(rng, cid, contract, amount, retain)
            if close_type == "사임" and amount and rng.random() < 0.6 and closed <= END_DATE:
                refunds.append((cid, closed.isoformat(), -int(round(amount * float(rng.uniform(0.1, 0.5)) / 10_000) * 10_000)))

        # 저액 일괄 등록: 성공보수만 약정한 건이 한 담당자 이름으로 한 번에 들어왔다.
        for _ in range(low_bulk):
            cid = next_id
            next_id += 1
            t = minor_index["손해배상"] - 1
            consults.append((cid, 1, 1, t + 1, 1, "방문", None, SUMMARY_TEMPLATES["손해배상"][0], d.isoformat(),
                             d.isoformat(), d.isoformat(), d.isoformat(), None, "성공보수만", 0, 3_000_000))
            engagements.append((cid, "정상", 0, None, None, 0))
            eng_cases.append((cid, t + 1))
        d += timedelta(days=1)

    conn.executemany("INSERT INTO consultation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", consults)
    conn.executemany("INSERT INTO engagement VALUES (?,?,?,?,?,?)", engagements)
    conn.executemany("INSERT INTO engagement_case VALUES (?,?)", eng_cases)
    conn.executemany("INSERT INTO installment (engagement_id, seq, due_date, amount, paid_date) VALUES (?,?,?,?,?)", installments)
    conn.executemany("INSERT INTO refund (engagement_id, refund_date, amount) VALUES (?,?,?)", refunds)
    conn.executemany("INSERT INTO holiday VALUES (?)", [(h,) for h in HOLIDAYS])

    # 콘텐츠: 사례는 유형이 붙어 있고 일부는 비공개, 영상은 유형 메타데이터가 없다.
    contents = []
    for i, (major, minor, *_rest) in enumerate(CASE_TYPES):
        for k in range(int(rng.integers(2, 6))):
            text = str(rng.choice(SUMMARY_TEMPLATES[minor]))
            outcome = rng.choice(["원만히 합의했다", "청구가 인용되었다", "불기소 처분을 받았다", "조정이 성립했다"])
            contents.append(("사례", i + 1, f"{minor} 사례 {k + 1}", f"{text}. 증거를 정리해 대응했고 {outcome}.",
                             int(rng.random() < 0.85)))
    for k, minor in enumerate(rng.choice([t[1] for t in CASE_TYPES], size=24)):
        contents.append(("영상", None, f"{minor} 대응 가이드 {k + 1}",
                         f"{rng.choice(SUMMARY_TEMPLATES[str(minor)])}면 먼저 확인할 것들", 1))
    conn.executemany("INSERT INTO content (kind, case_type_id, title, body, is_public) VALUES (?,?,?,?,?)", contents)

    # 월 목표: 직전 3개월 온라인 신규 사건 입금 평균 × 1.05. 앞선 달이 모자라면 전체 월평균 × 1.04.
    monthly = conn.execute(
        """SELECT SUBSTR(i.paid_date, 1, 7) AS m, SUM(i.amount) FROM installment i
           JOIN engagement e ON e.id = i.engagement_id JOIN consultation c ON c.id = e.id
           WHERE c.referrer IS NULL AND e.pay_status = '정상' AND e.terminated = 0 AND i.paid_date IS NOT NULL
             AND i.paid_date < ? GROUP BY m ORDER BY m""", (END_DATE.replace(day=1).isoformat(),)).fetchall()
    by_month = dict(monthly)
    avg = sum(v for _, v in monthly[1:]) / max(1, len(monthly) - 1)
    m = date(START_DATE.year, START_DATE.month, 1)
    targets = []
    while m <= END_DATE:
        prev = [by_month.get(_months_after(m, -k).strftime("%Y-%m")) for k in (1, 2, 3)]
        base = sum(prev) / 3 * 1.05 if all(prev) else avg * 1.04
        targets.append((m.strftime("%Y-%m"), int(round(base / 10_000_000) * 10_000_000)))
        m = _months_after(m, 1).replace(day=1)
    conn.executemany("INSERT INTO monthly_target VALUES (?, ?)", targets)
    conn.commit()

    n = conn.execute("SELECT COUNT(*), COUNT(contract_date) FROM consultation").fetchone()
    conn.close()
    print(f"DB 생성 완료: {path}")
    print(f"  상담 {n[0]:,}건 / 선임 {n[1]:,}건 / 기간 {START_DATE} ~ {END_DATE}")
    print(f"  분할 납부 {len(installments):,}회차 / 사건 묶음 {len(eng_cases):,}행 / 콘텐츠 {len(contents)}건")
    return path


if __name__ == "__main__":
    generate(Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH)
