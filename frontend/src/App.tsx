import { useCallback, useEffect, useState } from "react";
import KpiCard from "./components/KpiCard";
import FunnelChart from "./components/FunnelChart";
import TrendChart from "./components/TrendChart";
import DrilldownTable from "./components/DrilldownTable";
import AnomalyBanner from "./components/AnomalyBanner";
import ForecastCard from "./components/ForecastCard";
import {
  api, shiftDate, won,
  type AnomalyResponse, type DrilldownRow, type ForecastResponse,
  type Meta, type SnapshotResponse,
} from "./lib/api";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [target, setTarget] = useState<string>("");
  const [dimension, setDimension] = useState("branch");

  const [snapshot, setSnapshot] = useState<SnapshotResponse | null>(null);
  const [drilldown, setDrilldown] = useState<DrilldownRow[]>([]);
  const [anomaly, setAnomaly] = useState<AnomalyResponse | null>(null);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(true);

  // 최초 1회: 데이터 범위를 받아 마지막 날짜를 기본 조회일로 잡는다.
  useEffect(() => {
    api.meta()
      .then((m) => { setMeta(m); setTarget(m.end); })
      .catch((e) => { setError(String(e)); setLoading(false); });
  }, []);

  const load = useCallback(async () => {
    if (!target) return;
    setLoading(true);
    setError("");
    try {
      const start = shiftDate(target, -29);
      const [snap, drill, anom, fc] = await Promise.all([
        api.snapshot(target),
        api.drilldown(dimension, start, target),
        api.anomaly(target),
        api.forecast(target),
      ]);
      setSnapshot(snap);
      setDrilldown(drill.rows);
      setAnomaly(anom);
      setForecast(fc);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [target, dimension]);

  useEffect(() => { void load(); }, [load]);

  if (error) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-5">
          <h1 className="text-sm font-semibold text-rose-800">데이터를 불러오지 못했습니다</h1>
          <p className="mt-1 text-xs text-rose-700">{error}</p>
          <pre className="mt-3 overflow-x-auto rounded-lg bg-white p-3 text-[11px] text-slate-600">
{`# 1. 데이터 생성
python backend/scripts/generate_data.py

# 2. API 서버 기동 (backend/ 에서)
uvicorn app.main:app --reload --port 8000`}
          </pre>
        </div>
      </div>
    );
  }

  const cur = snapshot?.current;
  const delta = snapshot?.delta_pct ?? {};
  const base = snapshot?.baseline ?? {};

  return (
    <div className="mx-auto max-w-6xl px-5 py-7">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-slate-900">상담 전환 퍼널 BI</h1>
          <p className="mt-0.5 text-xs text-slate-500">
            콜 → 예약 → 방문 → 계약
            {meta && ` · 합성 데이터 ${meta.total_consultations.toLocaleString()}건 (${meta.start} ~ ${meta.end})`}
          </p>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setTarget((t) => shiftDate(t, -1))}
            className="rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
          >
            ← 전일
          </button>
          <input
            type="date"
            value={target}
            min={meta?.start}
            max={meta?.end}
            onChange={(e) => setTarget(e.target.value)}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800"
          />
          <button
            onClick={() => setTarget((t) => shiftDate(t, 1))}
            disabled={!!meta && target >= meta.end}
            className="rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
          >
            익일 →
          </button>
        </div>
      </header>

      {loading && !cur ? (
        <div className="mt-16 text-center text-sm text-slate-400">불러오는 중…</div>
      ) : (
        <main className={`mt-5 space-y-4 transition-opacity ${loading ? "opacity-60" : ""}`}>
          {anomaly && <AnomalyBanner data={anomaly} />}

          {cur && (
            <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <KpiCard label="콜 인입" value={cur.calls} suffix="건"
                deltaPct={delta.calls} baseline={base.calls} />
              <KpiCard label="예약" value={cur.reservations} suffix="건"
                deltaPct={delta.reservations} baseline={base.reservations}
                hint={`예약 전환율 ${cur.reservation_rate}%`} />
              <KpiCard label="계약" value={cur.contracts} suffix="건"
                deltaPct={delta.contracts} baseline={base.contracts}
                hint={`최종 전환율 ${cur.overall_rate}%`} />
              <KpiCard label="계약금액" value={Math.round(cur.revenue / 10000)} suffix="만원"
                deltaPct={delta.revenue}
                hint={`콜당 매출 ${won(cur.revenue_per_call)}원`} />
            </section>
          )}

          <section className="grid gap-4 lg:grid-cols-2">
            {cur && <FunnelChart data={cur} />}
            {snapshot && <TrendChart history={snapshot.history} current={snapshot.current} />}
          </section>

          <section className="grid gap-4 lg:grid-cols-2">
            <DrilldownTable rows={drilldown} dimension={dimension} onChange={setDimension} />
            {forecast && <ForecastCard data={forecast} />}
          </section>

          <p className="pt-2 text-center text-[11px] text-slate-400">
            모든 데이터는 시드 고정 난수로 생성한 합성 데이터입니다. 실제 조직·고객 정보를 포함하지 않습니다.
          </p>
        </main>
      )}
    </div>
  );
}
