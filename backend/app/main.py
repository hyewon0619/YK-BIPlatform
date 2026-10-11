"""사내 BI 플랫폼 — API 서버.

화면 요청은 읽기 전용 원천을 바로 읽고, 외부 모델을 부르지 않는다. 응답 시간이 예측 가능해야 하기 때문이다.
모든 라우트는 권한을 선언해야 하며, 선언이 없으면 서버가 뜨지 않는다(auth.check_routes).

실행:
    uvicorn app.main:app --reload --port 8000   (backend/ 디렉터리에서)
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import auth
from .auth import public, require_login, require_menu
from .db import query_one
from .services import decompose, drilldown, forecast, funnel, monitoring, recommend, success_fee

app = FastAPI(title="사내 BI 플랫폼", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

GRAIN = Query("daily", pattern="^(daily|weekly|monthly)$")


def _parse(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"날짜 형식이 잘못되었습니다: {value} (YYYY-MM-DD)")


def _latest() -> date:
    return date.fromisoformat(query_one("SELECT MAX(call_date) AS d FROM consultation")["d"])


# ── 공통 ────────────────────────────────────────────────────────────

@app.get("/api/meta", dependencies=[Depends(public)])
def meta() -> dict:
    row = query_one("SELECT MIN(call_date) AS start, MAX(call_date) AS end, COUNT(*) AS total FROM consultation")
    return {"start": row["start"], "end": row["end"], "total_consultations": row["total"],
            "dimensions": list(drilldown.DIMENSIONS), "decompose_dimensions": decompose.DIMENSIONS,
            "metrics": {m.key: m.label for m in monitoring.METRICS}}


@app.get("/api/me/menus")
def my_menus(user: auth.User = Depends(require_login)) -> dict:
    try:
        return {"user": user.name, "menus": auth.allowed_menus(user)}
    except Exception:  # noqa: BLE001 — 권한 표를 못 읽으면 빈 목록. 실패를 허용으로 처리하지 않는다.
        return {"user": user.name, "menus": []}


# ── ④ 경영 모니터링 ─────────────────────────────────────────────────

@app.get("/api/monitoring/highlights", dependencies=[Depends(require_menu("monitoring"))])
def highlights(target: str | None = None, grain: str = GRAIN, exclude: bool = False) -> dict:
    return monitoring.highlights(_parse(target, _latest()), grain, exclude)


@app.get("/api/monitoring/why", dependencies=[Depends(require_menu("monitoring"))])
def why(metric: str, dimension: str = "case_major", target: str | None = None, grain: str = GRAIN,
        exclude: bool = False, parent: str | None = None) -> dict:
    try:
        return decompose.breakdown(_parse(target, _latest()), metric, dimension, grain, exclude, parent)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── 상담 퍼널 ────────────────────────────────────────────────────────

@app.get("/api/funnel/snapshot", dependencies=[Depends(require_menu("funnel"))])
def funnel_snapshot(target: str | None = None, weeks: int = Query(12, ge=2, le=52)) -> dict:
    return funnel.weekday_trend(_parse(target, _latest()), weeks=weeks)


@app.get("/api/funnel/series", dependencies=[Depends(require_menu("funnel"))])
def funnel_series(start: str | None = None, end: str | None = None) -> list[dict]:
    end_d = _parse(end, _latest())
    return funnel.daily_series(_parse(start, end_d - timedelta(days=89)), end_d)


@app.get("/api/drilldown", dependencies=[Depends(require_menu("funnel"))])
def drilldown_by(dimension: str = "branch", start: str | None = None, end: str | None = None) -> dict:
    end_d = _parse(end, _latest())
    try:
        return drilldown.by_dimension(dimension, _parse(start, end_d - timedelta(days=29)), end_d)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── ① 매출 ──────────────────────────────────────────────────────────

@app.get("/api/forecast/revenue", dependencies=[Depends(require_menu("forecast"))])
def forecast_revenue(as_of: str | None = None, view: str = Query("current", pattern="^(current|previous)$")) -> dict:
    as_of_d = _parse(as_of, _latest())
    if view == "previous":
        # 지난달은 끝난 달이라 예측 카드를 숨기고 확정 입금만 보여 준다.
        last = as_of_d.replace(day=1) - timedelta(days=1)
        return {"view": "previous", "month": last.strftime("%Y-%m"),
                "confirmed": forecast.confirmed(last.replace(day=1), last)}
    result = forecast.revenue(as_of_d)
    result["view"] = "current"
    result["history"] = forecast.monthly_actuals(as_of_d)
    return result


@app.get("/api/forecast/backtest", dependencies=[Depends(require_menu("forecast"))])
def forecast_backtest(as_of: str | None = None, months: int = Query(6, ge=1, le=12)) -> dict:
    return forecast.backtest(_parse(as_of, _latest()), months=months)


@app.get("/api/forecast/success-fee", dependencies=[Depends(require_menu("success_fee"))])
def success_fee_estimate() -> dict:
    return success_fee.estimate()


# ── ② 별건 추천 ─────────────────────────────────────────────────────

@app.get("/api/recommend/targets", dependencies=[Depends(require_menu("recommend"))])
def recommend_targets(as_of: str | None = None) -> list[dict]:
    return recommend.recent_targets(_parse(as_of, _latest()).isoformat())


@app.get("/api/recommend/{engagement_id}", dependencies=[Depends(require_menu("recommend"))])
def recommend_for(engagement_id: int) -> dict:
    return recommend.for_engagement(engagement_id)


auth.check_routes(app)
