import hashlib
import json

import pytest

from app.db import query
from app.services import leads, recommend


def test_conditional_probability_matches_manual_count():
    co = recommend.cooccurrence()
    types = {r["minor"]: r["id"] for r in query("SELECT id, minor FROM case_type")}
    a, b = types["재판이혼"], types["재산분할"]
    n_a = query("SELECT COUNT(DISTINCT engagement_id) AS n FROM engagement_case WHERE case_type_id = :a", {"a": a})[0]["n"]
    n_ab = query(
        """SELECT COUNT(*) AS n FROM engagement_case x JOIN engagement_case y ON x.engagement_id = y.engagement_id
           WHERE x.case_type_id = :a AND y.case_type_id = :b""", {"a": a, "b": b})[0]["n"]
    rec = next(r for r in recommend.recommend_types([a]) if r["case_type_id"] == b)
    assert co["single"][a] == n_a and rec["pair_count"] == n_ab
    assert rec["probability"] == pytest.approx(n_ab / n_a, abs=1e-3)


def test_owned_types_and_rare_pairs_are_not_recommended(monkeypatch):
    monkeypatch.setattr(recommend, "cooccurrence", lambda: {"single": {1: 10, 2: 5, 3: 4}, "pair": {
        (1, 2): 5, (2, 1): 5, (1, 3): 1, (3, 1): 1}})
    monkeypatch.setattr(recommend, "case_types", lambda: {
        1: {"major": "x", "minor": "a"}, 2: {"major": "x", "minor": "b"}, 3: {"major": "x", "minor": "c"}})
    out = recommend.recommend_types([1])
    assert [r["case_type_id"] for r in out] == [2]  # 3 은 지지도 미달
    assert recommend.recommend_types([1, 2]) == []


def test_videos_are_not_repeated_across_labels():
    for t in recommend.recent_targets("2026-09-15", days=60, limit=200):
        res = recommend.for_engagement(t["engagement_id"])
        vids = [c["content_id"] for r in res["recommendations"] for c in r["contents"] if c["kind"] == "영상"]
        assert len(vids) == len(set(vids))
        for r in res["recommendations"]:
            assert sum(c["kind"] == "영상" for c in r["contents"]) <= 1


def test_contents_fill_with_wider_scope_instead_of_empty():
    any_type = query("SELECT id FROM case_type LIMIT 1")[0]["id"]
    out = recommend.match_contents(any_type, "보증금을 돌려받지 못하고 있다", set(), per_type=10)
    assert len(out) == 10
    assert any(c["match_level"] in ("같은 대분류", "전체") for c in out)
    assert all(c["url"] is None for c in out if c["kind"] == "사례" and
               query("SELECT is_public FROM content WHERE id = :i", {"i": c["content_id"]})[0]["is_public"] == 0)


# ── C. LLM 출력 검증 규칙 ───────────────────────────────────────────

def _block(seq, text):
    return leads.Block(seq, text, len(text), hashlib.sha256(text.encode()).hexdigest())


def test_source_must_be_complete_before_calling_the_model():
    ok, _ = leads.source_ready([_block(0, "가"), _block(1, "나")])
    assert ok
    assert not leads.source_ready([_block(0, "가"), _block(2, "다")])[0]
    broken = leads.Block(0, "가나", 2, "deadbeef")
    assert "해시" in leads.source_ready([broken])[1]


def test_model_routing_and_retry_backoff():
    small, big = "가" * 1000, "가" * 60000
    assert leads.estimate_tokens("가" * 6) == 5
    assert leads.route(small, 8192, 1024, 128000, 4096) == "local"
    assert leads.route(big, 8192, 1024, 128000, 4096) == "remote"
    assert leads.route("가" * 200000, 8192, 1024, 128000, 4096) == "too_large"
    assert [leads.retry_wait(n) for n in (0, 1, 7, 20)] == [30, 60, 3600, 3600]


def test_invented_quotes_and_unknown_types_are_dropped():
    source = "의뢰인은 이혼 소송 중이며, 별도로 전 직장에서 퇴직금을 받지 못했다고 말했다."
    raw = json.dumps({"candidates": [
        {"type_id": 13, "dispute": "임금체불", "quote": "전 직장에서 퇴직금을  받지 못했다"},
        {"type_id": 13, "dispute": "임금체불", "quote": "회사가 월급을 3개월 밀렸다"},
        {"type_id": 99, "dispute": "?", "quote": "이혼 소송"},
        {"type_id": 13, "dispute": "임금체불", "quote": "전 직장에서 퇴직금을 받지 못했다"},
    ]}, ensure_ascii=False)
    out = leads.validate(raw, source, allowed_type_ids={13})
    assert len(out) == 1 and out[0]["dispute"] == "임금체불"


def test_broken_format_is_a_failure_not_an_empty_result():
    with pytest.raises(leads.FormatError):
        leads.validate("후보 없음", "원문", {1})
    assert leads.validate('{"candidates": []}', "원문", {1}) == []


def test_only_latest_evidence_per_case_and_key():
    ev = [{"case_id": 1, "key": "k", "version": 1}, {"case_id": 1, "key": "k", "version": 3},
          {"case_id": 2, "key": "k", "version": 1}]
    out = leads.latest_per_key(ev)
    assert [(e["case_id"], e["version"]) for e in out] == [(1, 3), (2, 1)]
