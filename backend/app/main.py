"""상담 전환 퍼널 BI — API 서버.

실행:
    uvicorn app.main:app --reload --port 8000   (backend/ 디렉터리에서)
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .db import query_one
from .services import anomaly, drilldown, forecast, funnel

app = FastAPI(
    title="Consult Funnel BI",
    description="콜 → 예약 → 방문 → 계약 전환 퍼널 분석 API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _parse(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"날짜 형식이 잘못되었습니다: {value} (YYYY-MM-DD)")


def _latest_date() -> date:
    row = query_one("SELECT MAX(call_date) AS d FROM consultation")
    return date.fromisoformat(row["d"])


@app.get("/api/meta", summary="데이터 범위")
def meta() -> dict:
    row = query_one(
        """
        SELECT MIN(call_date) AS start, MAX(call_date) AS end, COUNT(*) AS total
        FROM consultation
        """
    )
    return {
        "start": row["start"],
        "end": row["end"],
        "total_consultations": row["total"],
        "dimensions": list(drilldown.DIMENSIONS),
    }


@app.get("/api/funnel/snapshot", summary="일간 퍼널 + 최근 N주 같은 요일 비교")
def funnel_snapshot(
    target: str | None = None,
    weeks: int = Query(12, ge=2, le=52),
) -> dict:
    return funnel.weekday_trend(_parse(target, _latest_date()), weeks=weeks)


@app.get("/api/funnel/period", summary="기간 합계 퍼널")
def funnel_period(start: str | None = None, end: str | None = None) -> dict:
    end_d = _parse(end, _latest_date())
    start_d = _parse(start, end_d - timedelta(days=29))
    if start_d > end_d:
        raise HTTPException(400, "start 가 end 보다 늦습니다.")
    return funnel.period(start_d, end_d)


@app.get("/api/funnel/series", summary="일자별 시계열")
def funnel_series(start: str | None = None, end: str | None = None) -> list[dict]:
    end_d = _parse(end, _latest_date())
    start_d = _parse(start, end_d - timedelta(days=89))
    return funnel.daily_series(start_d, end_d)


@app.get("/api/drilldown", summary="차원별 드릴다운")
def drilldown_by(
    dimension: str = Query("branch"),
    start: str | None = None,
    end: str | None = None,
) -> dict:
    end_d = _parse(end, _latest_date())
    start_d = _parse(start, end_d - timedelta(days=29))
    try:
        return drilldown.by_dimension(dimension, start_d, end_d)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/drilldown/cancel-reasons", summary="이탈 사유 분포")
def cancel_reasons(start: str | None = None, end: str | None = None) -> dict:
    end_d = _parse(end, _latest_date())
    start_d = _parse(start, end_d - timedelta(days=29))
    return drilldown.cancel_reasons(start_d, end_d)


@app.get("/api/anomaly", summary="특정 일자 이상 탐지")
def anomaly_detect(
    target: str | None = None,
    weeks: int = Query(12, ge=4, le=52),
    threshold: float = Query(3.5, ge=1.0, le=10.0),
    min_metrics: int = Query(2, ge=1, le=5),
) -> dict:
    return anomaly.detect(
        _parse(target, _latest_date()), weeks=weeks, threshold=threshold, min_metrics=min_metrics
    )


@app.get("/api/anomaly/scan", summary="구간 이상 일자 스캔")
def anomaly_scan(
    start: str | None = None,
    end: str | None = None,
    threshold: float = Query(3.5, ge=1.0, le=10.0),
    min_metrics: int = Query(2, ge=1, le=5),
) -> dict:
    end_d = _parse(end, _latest_date())
    start_d = _parse(start, end_d - timedelta(days=89))
    if (end_d - start_d).days > 400:
        raise HTTPException(400, "스캔 구간은 400일을 넘을 수 없습니다.")
    return anomaly.scan(start_d, end_d, threshold=threshold, min_metrics=min_metrics)


@app.get("/api/forecast/revenue", summary="당월 매출 예측")
def forecast_revenue(as_of: str | None = None, months_back: int = Query(12, ge=3, le=24)) -> dict:
    as_of_d = _parse(as_of, _latest_date())
    result = forecast.revenue(as_of_d, months_back=months_back)
    result["history"] = forecast.revenue_history(as_of_d, months=months_back)
    return result
