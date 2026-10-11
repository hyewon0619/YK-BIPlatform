import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth, main

client = TestClient(main.app)


def h(user):
    return {"X-User": user}


def test_every_route_declares_a_permission():
    auth.check_routes(main.app)
    bare = FastAPI()

    @bare.get("/oops")
    def oops():
        return {}

    with pytest.raises(RuntimeError, match="/oops"):
        auth.check_routes(bare)


def test_menu_catalog_comes_from_the_frontend_sidebar_file():
    assert auth.catalog()["forecast"] == "revenue"
    assert "monitoring" in auth.catalog()


def test_unknown_key_and_group_key_cannot_open_a_leaf():
    finance = auth.DEMO_USERS["finance"]
    assert auth.can_open(finance, "forecast")
    assert not auth.can_open(finance, "monitoring")
    assert not auth.can_open(finance, "revenue")  # 그룹 키로 리프를 열 수 없다
    assert not auth.can_open(auth.DEMO_USERS["admin"], "not-a-menu")


def test_group_key_equal_to_leaf_is_not_attached(monkeypatch):
    monkeypatch.setattr(auth, "catalog", lambda: {"report": "report", "daily": "report"})
    user = auth.User("u", "u", "user", frozenset({"report"}))
    assert auth.allowed_menus(user) == ["home", "report"]


def test_api_enforces_menu_permissions():
    assert client.get("/api/monitoring/highlights").status_code == 401
    assert client.get("/api/monitoring/highlights", headers=h("finance")).status_code == 403
    assert client.get("/api/forecast/revenue", headers=h("finance")).status_code == 200
    assert client.get("/api/monitoring/highlights", headers=h("admin")).status_code == 200
    assert client.get("/api/meta").status_code == 200


def test_permission_lookup_failure_returns_empty_not_everything(monkeypatch):
    def boom(_user):
        raise RuntimeError("권한 표를 읽지 못함")
    monkeypatch.setattr(auth, "allowed_menus", boom)
    assert client.get("/api/me/menus", headers=h("sales")).json()["menus"] == []


def test_previous_month_view_hides_forecast():
    prev = client.get("/api/forecast/revenue?view=previous", headers=h("admin")).json()
    assert prev["view"] == "previous" and "forecast" not in prev


def test_why_endpoint_rejects_unknown_dimension():
    r = client.get("/api/monitoring/why?metric=calls&dimension=drop_table", headers=h("admin"))
    assert r.status_code == 400
