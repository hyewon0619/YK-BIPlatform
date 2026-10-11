"""성공보수 실현 추정(별도 화면). 아직 받지 않은 성공보수 약정의 기대값.

    Ŝ = Σ 최대 예상 성공보수 × p_발생 × 수령비율
    p_발생   = 발생 건 / 실질 종결 건
    수령비율 = Σ 발생액 / Σ 발생 건의 예상액

설계 판단
- 종결일 코호트를 쓰지 않는다. 성공보수는 늦게 발생해서, 최근 기간을 종결일로 자르면 아직
  진행 중인 건(우측 절단) 때문에 확률이 낮게 나온다.
- 사임·소취하·합의처럼 성공보수가 생길 수 없는 종결은 표본에서 뺀다("실질 종결").
- 수령비율 분모는 발생한 건만 쓴다. 전체 예상액을 분모로 두면 발생확률이 두 번 곱해진다.
- 예상액 기재 건으로 표본을 거르지 않는다. 기재 여부 자체가 발생과 상관돼 선택 편향이 생긴다.
- 분류 조합 표본이 20건에 못 미치면 상위 분류로 올라간다.
"""

from __future__ import annotations

from ..db import query

MIN_SAMPLES = 20
NO_FEE_CLOSES = ("사임", "소취하", "합의")
LEVELS = (("minor", "consult_type"), ("minor",), ("major",), ())


def _key(row: dict, level: tuple) -> tuple:
    return tuple(row[k] for k in level)


def estimate() -> dict:
    closed = query(
        f"""
        SELECT t.major, t.minor, c.consult_type, c.sf_expected AS expected, e.sf_occurred AS occurred
        FROM engagement e JOIN consultation c ON c.id = e.id JOIN case_type t ON t.id = c.case_type_id
        WHERE e.closed_date IS NOT NULL AND e.close_type NOT IN ({', '.join(repr(x) for x in NO_FEE_CLOSES)})
          AND c.retain_type IN ('착수금+성공보수', '성공보수만')
        """
    )
    stats: dict[tuple, dict[tuple, list]] = {lv: {} for lv in LEVELS}
    for r in closed:
        for lv in LEVELS:
            s = stats[lv].setdefault(_key(r, lv), [0, 0, 0, 0])  # 종결, 발생, 발생액, 발생건 예상액
            s[0] += 1
            if r["occurred"] > 0:
                s[1] += 1
                s[2] += r["occurred"]
                s[3] += r["expected"]

    def params(row: dict) -> tuple[float, float, str]:
        for lv in LEVELS:
            s = stats[lv].get(_key(row, lv))
            if s and s[0] >= MIN_SAMPLES:
                p = s[1] / s[0]
                ratio = s[2] / s[3] if s[3] else 0.0
                return p, ratio, "·".join(lv) or "전체"
        return 0.0, 0.0, "표본 없음"

    pending = query(
        """
        SELECT t.major, t.minor, c.consult_type, c.sf_expected AS expected
        FROM engagement e JOIN consultation c ON c.id = e.id JOIN case_type t ON t.id = c.case_type_id
        WHERE e.closed_date IS NULL AND e.terminated = 0 AND c.sf_expected > 0
        """
    )
    total, by_major, levels_used = 0.0, {}, {}
    for r in pending:
        p, ratio, level = params(r)
        v = r["expected"] * p * ratio
        total += v
        by_major[r["major"]] = by_major.get(r["major"], 0.0) + v
        levels_used[level] = levels_used.get(level, 0) + 1
    return {
        "pending_count": len(pending),
        "pending_max": sum(r["expected"] for r in pending),
        "expected": int(round(total)),
        "by_major": {k: int(round(v)) for k, v in sorted(by_major.items(), key=lambda kv: -kv[1])},
        "levels_used": levels_used,
    }
