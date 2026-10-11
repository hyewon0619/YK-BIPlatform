"""③ 권한 — 기본 거부.

모든 라우트는 메뉴 권한(require_menu)·로그인(require_login)·공개(public) 중 하나를 선언해야 한다.
서버가 뜰 때 의존성 트리를 훑어 선언이 없는 라우트가 있으면 기동하지 않는다(check_routes).

메뉴 정의는 한 곳이다. 서버가 프런트의 사이드바 정의 파일(frontend/src/menu.json)을 직접 읽어
메뉴 키 목록을 만든다. 별도 등록 절차가 없다.

판정 순서: 홈 → 카탈로그에 없는 키 거부 → 관리자 허용 → 허용 행 확인.
허용된 리프의 상위 그룹 키는 자동으로 붙이되, 그룹 키가 리프 키와 같으면 붙이지 않는다.
그룹 키가 리프 키와 같았을 때, 그룹 허용이 리프 허용이 되어 메뉴 하나만 허용해도 다른 화면이 열렸다.

권한 조회가 실패하면 서버는 빈 목록을 돌려주고, 프런트는 실패 시 홈만 연다. 실패를 허용으로 처리하면
권한 표를 못 읽는 순간 모든 메뉴가 열린다. 사용자 권한은 캐시하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.routing import APIRoute

MENU_FILE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "menu.json"
HOME = "home"


@lru_cache(maxsize=1)
def catalog() -> dict[str, str]:
    """리프 메뉴 키 → 그룹 키."""
    data = json.loads(MENU_FILE.read_text(encoding="utf-8"))
    return {item["key"]: group["key"] for group in data["groups"] for item in group["items"]}


@dataclass(frozen=True)
class User:
    id: str
    name: str
    role: str  # superadmin | admin | user
    allowed: frozenset[str] = field(default_factory=frozenset)


#: 데모 사용자. 실제 서비스에서는 사내 로그인과 권한 표(관리 계정만 쓰기 가능)에서 읽는다.
DEMO_USERS = {
    "admin": User("admin", "관리자", "admin"),
    "finance": User("finance", "재무팀", "user", frozenset({"forecast", "success_fee"})),
    "sales": User("sales", "영업팀", "user", frozenset({"recommend", "funnel"})),
}


def load_user(user_id: str) -> User | None:
    return DEMO_USERS.get(user_id)


def allowed_menus(user: User) -> list[str]:
    """화면에 보여 줄 메뉴 키. 리프에 그룹 키를 붙이되, 리프와 같은 그룹 키는 붙이지 않는다."""
    cat = catalog()
    leaves = set(cat) if user.role in ("superadmin", "admin") else {k for k in user.allowed if k in cat}
    groups = {cat[k] for k in leaves if cat[k] != k}
    return sorted({HOME} | leaves | groups)


def can_open(user: User, menu: str) -> bool:
    if menu == HOME:
        return True
    cat = catalog()
    if menu not in cat:
        return False  # 카탈로그에 없는 키는 거부한다. 그룹 키로 리프를 열 수도 없다.
    if user.role in ("superadmin", "admin"):
        return True
    return menu in user.allowed


# ── 라우트 선언 ─────────────────────────────────────────────────────

def current_user(x_user: str = Header(default="")) -> User:
    user = load_user(x_user)
    if user is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    return user


def require_login(user: User = Depends(current_user)) -> User:
    return user


def require_menu(menu: str):
    if menu not in catalog():
        raise RuntimeError(f"메뉴 정의에 없는 키입니다: {menu}")

    def dep(user: User = Depends(current_user)) -> User:
        if not can_open(user, menu):
            raise HTTPException(403, "이 메뉴를 볼 권한이 없습니다.")
        return user

    dep.__permission__ = f"menu:{menu}"
    return dep


def public() -> None:
    return None


require_login.__permission__ = "login"
public.__permission__ = "public"


def _declared(dependant) -> bool:
    if getattr(dependant.call, "__permission__", None):
        return True
    return any(_declared(d) for d in dependant.dependencies)


def check_routes(app: FastAPI) -> None:
    """선언이 없는 라우트가 하나라도 있으면 서버를 띄우지 않는다."""
    missing = [f"{','.join(sorted(r.methods))} {r.path}" for r in app.routes
               if isinstance(r, APIRoute) and not _declared(r.dependant)]
    if missing:
        raise RuntimeError("권한 선언이 없는 라우트가 있습니다: " + "; ".join(missing))
