"""프로세스 메모리 TTL 캐시.

계산 비용과 데이터 변화 속도에 맞춰 수명을 다르게 둔다. 사용자 권한은 캐시하지 않는다.
"""

from __future__ import annotations

import time
from functools import wraps
from typing import Callable

SNAPSHOT_TTL = 30          # 조회 스냅샷
CONTENT_TTL = 5 * 60       # 사례·메타
COOCCUR_TTL = 10 * 60      # 동시출현 집계·추천 목록

_store: dict[tuple, tuple[float, object]] = {}


def ttl_cache(seconds: int) -> Callable:
    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__module__, fn.__qualname__, args, tuple(sorted(kwargs.items())))
            hit = _store.get(key)
            now = time.monotonic()
            if hit and now - hit[0] < seconds:
                return hit[1]
            value = fn(*args, **kwargs)
            _store[key] = (now, value)
            return value
        return wrapper
    return deco


def clear() -> None:
    _store.clear()
