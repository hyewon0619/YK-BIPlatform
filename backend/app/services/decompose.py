"""④ 원인 분해 — 지표가 왜 움직였는지 합이 정확히 맞는 기여도로 쪼갠다.

평균 단가(부가가치) A/N 의 차이는 근사 없이 금액 효과와 건수 효과로 나뉜다.

    A1/N1 − A0/N0 = (A1 − A0)/N1  +  A0(N0 − N1)/(N1·N0)
                     금액 효과          건수 효과

차원 값 i 의 비중 s 와 단가 v 로 낸 기여도는 전부 더하면 전체 차이와 원 단위로 같다.

    c_i = s_i¹·v_i¹ − s_i⁰·v_i⁰,   Σ c_i = A1/N1 − A0/N0

선임률(선임 C ÷ 방문 V)은 Σ (v_i/V)(c_i/v_i) = C/V 덕분에 같은 방식으로 합이 맞는다. 각 행은
"어떤 고객이 왔나"(구성 효과)와 "같은 고객을 더 잘 잡았나"(전환 효과)로 다시 나누는데, 구성 효과에서
전체 평균 R̄ 를 뺀다. 빼지 않으면 선임률이 0 보다 크기만 해도 비중이 늘어난 행은 무조건 양(+)의 기여로
읽힌다. 평균보다 못한 집단의 비중이 늘어도 "긍정 기여"가 되는 것이다. 비중 변화의 합이 0 이라 R̄ 를
빼도 총합은 그대로다.

기준값은 기간별 값의 단순 평균이 아니라 기준 기간을 통째로 합산해 낸다. 그래야 기여도 합이 전체 차이와
맞는다. 카드의 단순 평균과 소수점 단위로 다를 수 있어 응답에 둘 다 싣는다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .monitoring import BY_KEY, _in, counts, excluded, metric_values, periods, snapshot_rows

DIMENSIONS = {
    "retain_type": "선임형태",
    "amount_bucket": "약정금 구간",
    "consult_type": "상담유형",
    "case_major": "사건 대분류",
    "case_minor": "사건 소분류",
    "channel": "유입경로",
    "lawyer": "상담변호사",
    "branch": "지점",
}
#: 사람 단위 차원은 표본이 적으면 선임률이 0% 아니면 100% 로 튀어 상위를 차지한다.
SMALL_SAMPLE_DIMS = {"lawyer"}
#: 선임된 건에만 있는 값. 선임률(방문 대비)은 이 차원으로 나눌 수 없다.
CONTRACT_ONLY_DIMS = {"retain_type", "amount_bucket"}
MIN_SAMPLE = 3
OTHER = "기타(표본 3건 미만)"
TOP_EXPLAIN = 3


def _groups(rows, rng, dim, exclude, metric_key):
    g = defaultdict(lambda: {"calls": 0, "reservations": 0, "visits": 0, "contracts": 0, "revenue": 0})
    for r in rows:
        k = r[dim] if r[dim] is not None else "(미선임)"
        if _in(r["call_date"], rng):
            g[k]["calls"] += 1
        if _in(r["reserved_date"], rng):
            g[k]["reservations"] += 1
        if _in(r["visit_date"], rng):
            g[k]["visits"] += 1
        if _in(r["contract_date"], rng) and not (exclude and excluded(r)):
            g[k]["contracts"] += 1
            g[k]["revenue"] += r["contract_amount"]
    return g


def _merge_small(cur, base, k, size_key):
    """표본이 작은 값을 '기타'로 묶는다. 합계는 그대로 보존된다."""
    keys = set(cur) | set(base)
    small = {key for key in keys if cur.get(key, {}).get(size_key, 0) < MIN_SAMPLE
             and base.get(key, {}).get(size_key, 0) / k < MIN_SAMPLE}
    for src in (cur, base):
        for key in small & set(src):
            dst = src.setdefault(OTHER, {f: 0 for f in src[key]})
            for f, v in src.pop(key).items():
                dst[f] += v


def breakdown(target: date, metric: str, dimension: str, grain: str = "daily",
              exclude: bool = False, parent: str | None = None) -> dict:
    if metric not in BY_KEY:
        raise ValueError(f"지원하지 않는 지표입니다: {metric}")
    if dimension not in DIMENSIONS:
        raise ValueError(f"지원하지 않는 차원입니다: {dimension} (가능: {', '.join(DIMENSIONS)})")
    cur_rng, base_rngs = periods(target, grain)
    rows = snapshot_rows((cur_rng, *base_rngs))
    if parent:  # 대분류에서 소분류로 내려가기
        rows = tuple(r for r in rows if r["case_major"] == parent)
    k = len(base_rngs)

    cur = _groups(rows, cur_rng, dimension, exclude, metric)
    base: dict = defaultdict(lambda: {"calls": 0, "reservations": 0, "visits": 0, "contracts": 0, "revenue": 0})
    for b in base_rngs:
        for key, v in _groups(rows, b, dimension, exclude, metric).items():
            for f, n in v.items():
                base[key][f] += n
    if dimension in SMALL_SAMPLE_DIMS:
        _merge_small(cur, base, k, "visits" if metric == "contract_rate" else "contracts")

    def total(g):
        return {f: sum(v[f] for v in g.values()) for f in ("calls", "reservations", "visits", "contracts", "revenue")}

    t1, t0 = total(cur), total(base)
    items, effects = [], None
    keys = sorted(set(cur) | set(base))
    zero = {"calls": 0, "reservations": 0, "visits": 0, "contracts": 0, "revenue": 0}

    if metric == "value_per_contract":
        a1, n1, a0, n0 = t1["revenue"], t1["contracts"], t0["revenue"], t0["contracts"]
        if not (n1 and n0):
            return _empty(metric, dimension, grain, cur_rng, "선임 건이 없어 분해할 수 없습니다.")
        y1, y0 = a1 / n1, a0 / n0
        # 기준을 "기간당 평균"으로 환산(A0/k, N0/k)해도 단가는 같다. 항등식은 환산된 값으로 쓴다.
        a0k, n0k = a0 / k, n0 / k
        effects = {"amount_effect": round((a1 - a0k) / n1, 1), "count_effect": round(a0k * (n0k - n1) / (n1 * n0k), 1)}
        for key in keys:
            c1, c0 = cur.get(key, zero), base.get(key, zero)
            contrib = c1["revenue"] / n1 - c0["revenue"] / n0
            items.append({"value": key, "contribution": round(contrib, 1),
                          "now": {"count": c1["contracts"], "amount": c1["revenue"]},
                          "base": {"count": round(c0["contracts"] / k, 2), "amount": round(c0["revenue"] / k)}})
    elif metric == "contract_rate":
        if dimension in CONTRACT_ONLY_DIMS:
            raise ValueError(f"선임률은 '{DIMENSIONS[dimension]}'로 나눌 수 없습니다. 방문 단계에는 그 값이 없습니다.")
        v1, v0 = t1["visits"], t0["visits"]
        if not (v1 and v0):
            return _empty(metric, dimension, grain, cur_rng, "방문 건이 없어 분해할 수 없습니다.")
        y1, y0 = t1["contracts"] / v1 * 100, t0["contracts"] / v0 * 100
        r_bar = (y1 + y0) / 2
        for key in keys:
            c1, c0 = cur.get(key, zero), base.get(key, zero)
            w1, w0 = c1["visits"] / v1, c0["visits"] / v0
            r1 = c1["contracts"] / c1["visits"] * 100 if c1["visits"] else None
            r0 = c0["contracts"] / c0["visits"] * 100 if c0["visits"] else None
            # 한쪽 기간에 방문이 없으면 그 기간의 전환율은 다른 쪽 값으로 둔다(비중이 0 이라 결과에 영향 없음).
            r1 = r0 if r1 is None else r1
            r0 = r1 if r0 is None else r0
            r1, r0 = r1 or 0.0, r0 or 0.0
            # 기여도는 건수로 바로 낸다. 방문과 선임은 각자 날짜축이라 방문 없이 선임만 있는 칸이 생기고,
            # 그 몫은 비중·전환율로 나눌 수 없어 전환 효과에 넣는다. 그래도 합은 그대로 맞는다.
            contrib = (c1["contracts"] / v1 - c0["contracts"] / v0) * 100
            mix = (w1 - w0) * ((r1 + r0) / 2 - r_bar)
            conv = contrib - mix
            items.append({"value": key, "contribution": round(contrib, 3),
                          "mix_effect": round(mix, 3), "conversion_effect": round(conv, 3),
                          "now": {"visits": c1["visits"], "contracts": c1["contracts"], "rate": round(r1, 1)},
                          "base": {"visits": round(c0["visits"] / k, 2), "rate": round(r0, 1)}})
    else:  # 건수·금액: 값별 차이가 곧 기여도다(기준은 기간 평균으로 환산).
        y1, y0 = t1[metric], t0[metric] / k
        for key in keys:
            c1, c0 = cur.get(key, zero), base.get(key, zero)
            items.append({"value": key, "contribution": round(c1[metric] - c0[metric] / k, 2),
                          "now": c1[metric], "base": round(c0[metric] / k, 2)})

    items.sort(key=lambda it: -abs(it["contribution"]))
    abs_sum = sum(abs(it["contribution"]) for it in items) or 1.0
    explained = sum(abs(it["contribution"]) for it in items[:TOP_EXPLAIN]) / abs_sum * 100
    card_base = _card_baseline(rows, base_rngs, metric, exclude)
    return {
        "metric": metric, "label": BY_KEY[metric].label, "dimension": dimension,
        "dimension_label": DIMENSIONS[dimension], "grain": grain, "parent": parent,
        "period": [cur_rng[0].isoformat(), cur_rng[1].isoformat()], "official": not exclude,
        "now": round(y1, 2), "baseline": round(y0, 2), "card_baseline": card_base,
        "difference": round(y1 - y0, 2),
        "sum_of_contributions": round(sum(it["contribution"] for it in items), 2),
        "effects": effects, "explained_top3_pct": round(explained, 1),
        "no_clear_cause": explained < 50, "items": items,
    }


def _card_baseline(rows, base_rngs, metric, exclude) -> float:
    """카드에 보이는 기준값(기간별 값의 단순 평균). 분해 기준값과 비교용으로 함께 낸다."""
    vals = [metric_values(counts(rows, b, exclude))[metric] for b in base_rngs]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


def _empty(metric, dimension, grain, rng, reason) -> dict:
    return {"metric": metric, "dimension": dimension, "grain": grain,
            "period": [rng[0].isoformat(), rng[1].isoformat()], "items": [], "message": reason}
