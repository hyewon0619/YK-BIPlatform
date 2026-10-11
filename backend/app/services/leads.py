"""② C. 원문 별건 단서 — LLM 출력을 믿지 않고 다시 검증하는 규칙.

사건 자료 원문에서 독립 분쟁을 찾는 일만 LLM 에 맡긴다(추출 → 독립성 검증 → 분류 확정, 10분 주기 배치).
모델 호출 자체는 공개본에 없고, 그 앞뒤를 감싸는 결정적 규칙만 옮겼다. 이 규칙들이 모델이 값을
지어내지 못하게 막는다.

- 원문은 블록별 길이·연속성·해시가 모두 맞아야 모델에 넣는다. 하나라도 틀리면 "원문 대기" 로 둔다.
- 입력 크기로 모델을 고른다. 작으면 로컬 모델, 크면 원격 대형 모델, 상한을 넘으면 부르지 않고 실패로 기록한다.
- 인용은 원문에 그대로 있어야 하고, 분류는 목록에 있는 ID 만 받는다.
- 응답 형식이 깨지면 "후보 없음"으로 조용히 넘기지 않고 재시도한다. 놓친 것과 없는 것을 구분하기 위해서다.
- 같은 근거는 (사건, 단서) 키로 최신 하나만 남긴다.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass

MAX_RETRY_WAIT = 3600


# ── 원문 무결성 ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class Block:
    seq: int
    text: str
    length: int
    sha256: str


def source_ready(blocks: list[Block]) -> tuple[bool, str]:
    """블록 순번이 0 부터 빠짐없이 이어지고, 길이·해시가 모두 맞아야 모델에 넣는다."""
    if not blocks:
        return False, "원문 대기: 블록 없음"
    for expected, b in enumerate(sorted(blocks, key=lambda x: x.seq)):
        if b.seq != expected:
            return False, f"원문 대기: {expected}번 블록 누락"
        if len(b.text) != b.length:
            return False, f"원문 대기: {b.seq}번 블록 길이 불일치"
        if hashlib.sha256(b.text.encode()).hexdigest() != b.sha256:
            return False, f"원문 대기: {b.seq}번 블록 해시 불일치"
    return True, "준비됨"


# ── 모델 라우팅과 재시도 ────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """토큰 수를 글자 수로 보수적으로 추정한다: ⌈5/6 · chars⌉."""
    return math.ceil(len(text) * 5 / 6)


def route(text: str, local_ctx: int, local_out: int, remote_ctx: int, remote_out: int) -> str:
    """문맥 창에서 출력과 템플릿 여유를 뺀 예산으로 모델을 고른다.

        reserve = min(1024, max(256, C/16)),  local if tok ≤ C − out − reserve
    """
    tok = estimate_tokens(text)

    def budget(ctx: int, out: int) -> int:
        return ctx - out - min(1024, max(256, ctx // 16))

    if tok <= budget(local_ctx, local_out):
        return "local"
    if tok <= budget(remote_ctx, remote_out):
        return "remote"
    return "too_large"  # 모델을 부르지 않고 실패로 기록한다.


def retry_wait(attempt: int) -> int:
    """재시도 대기(초) = min(3600, 30 · 2^min(n, 7))."""
    return min(MAX_RETRY_WAIT, 30 * 2 ** min(attempt, 7))


# ── 출력 검증 ───────────────────────────────────────────────────────

def norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def quote_in_source(quote: str, source: str) -> bool:
    """인용은 공백을 지우고 대소문자를 무시한 뒤 원문 안에 그대로 있어야 한다."""
    q = norm(quote)
    return bool(q) and q in norm(source)


def candidate_key(dispute_type: str, quote: str) -> str:
    return hashlib.sha256(f"{norm(dispute_type)}|{norm(quote)}".encode()).hexdigest()


class FormatError(Exception):
    """응답 형식 오류. "후보 없음"과 구분해 재시도한다."""


def validate(raw: str, source: str, allowed_type_ids: set[int]) -> list[dict]:
    """모델 응답을 검증해 통과한 후보만 돌려준다. 형식이 깨지면 FormatError."""
    try:
        data = json.loads(raw)
        cands = data["candidates"]
        if not isinstance(cands, list):
            raise TypeError
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise FormatError("응답 형식 오류 — 재시도 대상") from e

    out, seen = [], set()
    for c in cands:
        if not isinstance(c, dict):
            raise FormatError("후보 형식 오류 — 재시도 대상")
        if c.get("type_id") not in allowed_type_ids:
            continue  # 목록에 없는 분류는 받지 않는다.
        if not quote_in_source(str(c.get("quote", "")), source):
            continue  # 원문에 없는 인용은 지어낸 것이다.
        key = candidate_key(str(c.get("dispute", "")), str(c["quote"]))
        if key in seen:
            continue
        seen.add(key)
        out.append({"type_id": c["type_id"], "dispute": c.get("dispute"), "quote": c["quote"], "key": key})
    return out


def latest_per_key(evidence: list[dict]) -> list[dict]:
    """재구성 때마다 근거를 이어 붙이면 같은 근거가 여러 번 보인다. (사건, 단서) 키로 최신 하나만 남긴다."""
    best: dict[tuple, dict] = {}
    for e in evidence:
        k = (e["case_id"], e["key"])
        if k not in best or e["version"] > best[k]["version"]:
            best[k] = e
    return sorted(best.values(), key=lambda e: (e["case_id"], e["key"]))
