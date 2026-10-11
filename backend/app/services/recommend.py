"""② 별건 추천 — 기존 의뢰인에게 추가로 필요할 법한 사건을 찾아 업무 화면에 띄운다.

한 수임 안에 사건이 여러 개인 경우가 매출 단위다. 이혼 고객에게 재산분할·양육이, 형사 고소 고객에게
손해배상이 따라오는 식이다. 추천은 성격이 다른 세 갈래로 돌아간다.

  A. 동시출현 추천   과거 선임 패턴의 통계(규칙)          → 이 파일
  B. 근거 콘텐츠     상담 내용과 맞는 사례·영상 매칭        → 이 파일
  C. 원문 별건 단서  사건 원문에서 독립 분쟁 추출(LLM)     → leads.py (검증 규칙)

통계로 충분한 곳에는 모델을 쓰지 않는다. 어떤 유형을 추천할지는 과거 선임 빈도가 가장 설명하기 쉽다.
추천은 사람이 확인한 뒤 쓴다. 광고는 "등록"만 하고, 발송 직전에 마케팅 동의를 다시 확인한다.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from itertools import combinations

from ..cache import CONTENT_TTL, COOCCUR_TTL, ttl_cache
from ..db import query

MIN_PAIR = 2          # 지지도 하한. 우연한 동시출현을 버린다.
TOP_TYPES = 5
CONTENTS_PER_TYPE = 3


# ── A. 동시출현 ─────────────────────────────────────────────────────

@ttl_cache(COOCCUR_TTL)
def cooccurrence() -> dict:
    """수임 = 장바구니. 사건유형 쌍을 세어 조건부 확률 P(b|a) 를 만든다.

        P(b | a) = |{e : a, b ∈ B(e)}| / |{e : a ∈ B(e)}|,   pair(a, b) ≥ 2
    """
    baskets: dict[int, set[int]] = defaultdict(set)
    for r in query("SELECT engagement_id, case_type_id FROM engagement_case"):
        baskets[r["engagement_id"]].add(r["case_type_id"])
    single, pair = Counter(), Counter()
    for items in baskets.values():
        single.update(items)
        for a, b in combinations(sorted(items), 2):
            pair[(a, b)] += 1
            pair[(b, a)] += 1
    return {"single": dict(single), "pair": dict(pair)}


@ttl_cache(CONTENT_TTL)
def case_types() -> dict[int, dict]:
    return {r["id"]: r for r in query("SELECT id, major, minor FROM case_type")}


def recommend_types(owned: list[int], top: int = TOP_TYPES) -> list[dict]:
    """이미 가진 유형들로부터 추천 유형을 고른다. 동시출현 건수 → 확률 순으로 정렬한다."""
    co, types = cooccurrence(), case_types()
    best: dict[int, dict] = {}
    for a in owned:
        n_a = co["single"].get(a, 0)
        for (x, b), n_ab in co["pair"].items():
            if x != a or b in owned or n_ab < MIN_PAIR or not n_a:
                continue
            cand = {"case_type_id": b, "label": f"{types[b]['major']} > {types[b]['minor']}",
                    "because_of": types[a]["minor"], "pair_count": n_ab, "probability": round(n_ab / n_a, 3)}
            prev = best.get(b)
            if not prev or (cand["pair_count"], cand["probability"]) > (prev["pair_count"], prev["probability"]):
                best[b] = cand
    return sorted(best.values(), key=lambda c: (-c["pair_count"], -c["probability"]))[:top]


# ── B. 근거 콘텐츠 매칭 ──────────────────────────────────────────────
# 운영에서는 형태소 BM25(more_like_this)와 임베딩 kNN 을 검색엔진에서 썼다. 공개본은 외부 의존 없이
# 글자 2-gram TF-IDF 코사인을 임베딩 자리에 둔다. 정렬과 근거를 나누는 구조는 같다.

_TOKEN = re.compile(r"[가-힣A-Za-z0-9]+")


def tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text) if len(t) >= 2}


def _bigrams(text: str) -> Counter:
    s = re.sub(r"\s+", "", text)
    return Counter(s[i:i + 2] for i in range(len(s) - 1))


@ttl_cache(CONTENT_TTL)
def _index() -> tuple[list[dict], dict[str, float]]:
    docs = query("SELECT id, kind, case_type_id, title, body, is_public FROM content")
    df = Counter()
    for d in docs:
        d["grams"] = _bigrams(d["title"] + " " + d["body"])
        df.update(d["grams"].keys())
    idf = {g: math.log((1 + len(docs)) / (1 + n)) + 1 for g, n in df.items()}
    return docs, idf


def _vec(grams: Counter, idf: dict[str, float]) -> dict[str, float]:
    v = {g: c * idf.get(g, 1.0) for g, c in grams.items()}
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {g: x / norm for g, x in v.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(g, 0.0) for g, x in a.items())


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def match_contents(case_type_id: int, consult_text: str, used_videos: set[int],
                   per_type: int = CONTENTS_PER_TYPE) -> list[dict]:
    """추천 유형 하나에 붙일 사례·영상.

    질의는 "추천 유형명 + 상담 내용"을 합친다. 유형명만 쓰면 고객 사정이 빠지고, 상담만 쓰면 추천 유형과
    상관없이 같은 결과가 나온다. 정렬은 유사도로, 키워드 자카드는 "왜 이 사례인가"의 근거로만 쓴다.

    채우는 순서: 같은 유형(소분류) 유사도 순 → 같은 대분류 → 유형을 풀고 전체 유사도 순(비매칭 표시).
    빈 칸보다 넓힌 추천이 낫다. 영상은 유형 메타데이터가 없어 유사도 상위가 라벨마다 겹친다. 그래서 라벨마다
    한 건만, 아직 다른 라벨에 쓰지 않은 영상만 배정한다.
    """
    docs, idf = _index()
    types = case_types()
    t = types[case_type_id]
    q_text = f"{t['major']} {t['minor']} {consult_text}"
    q_vec, q_tok = _vec(_bigrams(q_text), idf), tokens(consult_text)
    same_major = {i for i, x in types.items() if x["major"] == t["major"]}

    scored = []
    for d in docs:
        if d["kind"] == "영상" and d["id"] in used_videos:
            continue
        sim = cosine(q_vec, _vec(d["grams"], idf))
        tier = 0 if d["case_type_id"] == case_type_id else 1 if d["case_type_id"] in same_major else 2
        if d["kind"] == "영상":
            tier = 1  # 영상은 유형 메타데이터가 없다. 같은 유형 사례 다음 순위에서 유사도로만 경쟁한다.
        scored.append((tier, -sim, d, sim))
    scored.sort(key=lambda x: (x[0], x[1]))

    out, video_taken = [], False
    for tier, _neg, d, sim in scored:
        if len(out) >= per_type:
            break
        if d["kind"] == "영상":
            if video_taken:
                continue  # 라벨마다 영상은 한 건. 같은 영상이 여러 라벨에 반복되지 않게 한다.
            video_taken = True
            used_videos.add(d["id"])
        out.append({
            "content_id": d["id"], "kind": d["kind"], "title": d["title"],
            "similarity": round(sim, 3), "keyword_overlap": round(jaccard(q_tok, tokens(d["body"])), 3),
            "matched": tier == 0,
            "match_level": "영상(유형 정보 없음)" if d["kind"] == "영상" else ("같은 유형", "같은 대분류", "전체")[tier],
            # 비공개 사례에 링크를 만들면 열리지 않는다. 링크 없이 보여준다.
            "url": f"/contents/{d['id']}" if d["is_public"] else None,
        })
    return out


def for_engagement(engagement_id: int) -> dict:
    """한 수임에 대한 추천: 추천 유형 상위 5개와 유형별 근거 콘텐츠."""
    rows = query(
        """SELECT ec.case_type_id, c.summary FROM engagement_case ec JOIN consultation c ON c.id = ec.engagement_id
           WHERE ec.engagement_id = :e""", {"e": engagement_id})
    if not rows:
        return {"engagement_id": engagement_id, "owned": [], "recommendations": []}
    owned = [r["case_type_id"] for r in rows]
    used_videos: set[int] = set()
    recs = recommend_types(owned)
    for rec in recs:
        rec["contents"] = match_contents(rec["case_type_id"], rows[0]["summary"], used_videos)
    types = case_types()
    return {"engagement_id": engagement_id,
            "owned": [f"{types[i]['major']} > {types[i]['minor']}" for i in owned],
            "recommendations": recs}


def recent_targets(as_of: str, days: int = 14, limit: int = 20) -> list[dict]:
    """추천 대상 예시: 최근 선임한 고객."""
    return query(
        """SELECT c.id AS engagement_id, c.contract_date, t.major, t.minor
           FROM consultation c JOIN case_type t ON t.id = c.case_type_id
           WHERE c.contract_date BETWEEN DATE(:as_of, :back) AND :as_of
           ORDER BY c.contract_date DESC, c.id DESC LIMIT :limit""",
        {"as_of": as_of, "back": f"-{days} days", "limit": limit},
    )
