import { useEffect, useState } from "react";
import DrilldownTable from "./components/DrilldownTable";
import ForecastCard, { SuccessFeeCard } from "./components/ForecastCard";
import FunnelChart from "./components/FunnelChart";
import KpiCard from "./components/KpiCard";
import Monitoring from "./components/Monitoring";
import RecommendPanel from "./components/RecommendPanel";
import TrendChart from "./components/TrendChart";
import menu from "./menu.json";
import { api, setUser, shiftDate, type DrilldownRow, type Meta, type SnapshotResponse } from "./lib/api";

const USERS = [
  { id: "admin", label: "관리자" },
  { id: "finance", label: "재무팀" },
  { id: "sales", label: "영업팀" },
];

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [user, setUserState] = useState("admin");
  const [allowed, setAllowed] = useState<string[]>(["home"]);
  const [page, setPage] = useState("monitoring");
  const [target, setTarget] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.meta().then((m) => { setMeta(m); setTarget(m.end); }).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    setUser(user);
    // 권한 조회가 실패하면 홈만 연다. 실패를 허용으로 처리하지 않는다.
    api.menus()
      .then((r) => {
        setAllowed(r.menus);
        const first = menu.groups.flatMap((g) => g.items).find((i) => r.menus.includes(i.key));
        setPage(first?.key ?? "home");
      })
      .catch(() => { setAllowed(["home"]); setPage("home"); });
  }, [user]);

  if (error) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-5 text-xs text-rose-700">
          <h1 className="text-sm font-semibold text-rose-800">데이터를 불러오지 못했습니다</h1>
          <p className="mt-1">{error}</p>
          <pre className="mt-3 rounded-lg bg-white p-3 text-[11px] text-slate-600">{`python backend/scripts/generate_data.py
cd backend && uvicorn app.main:app --reload --port 8000`}</pre>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <aside className="w-52 shrink-0 border-r border-slate-200 bg-white px-3 py-5">
        <div className="px-2 text-sm font-bold text-slate-900">사내 BI 플랫폼</div>
        <select value={user} onChange={(e) => setUserState(e.target.value)}
          className="mt-3 w-full rounded-md border border-slate-200 px-2 py-1 text-xs">
          {USERS.map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
        </select>
        <nav className="mt-4 space-y-4">
          {menu.groups.filter((g) => allowed.includes(g.key)).map((g) => (
            <div key={g.key}>
              <div className="px-2 text-[11px] font-semibold text-slate-400">{g.label}</div>
              {g.items.filter((i) => allowed.includes(i.key)).map((i) => (
                <button key={i.key} onClick={() => setPage(i.key)}
                  className={`mt-0.5 block w-full rounded-md px-2 py-1.5 text-left text-xs ${page === i.key ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100"}`}>
                  {i.label}
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <main className="min-w-0 flex-1 px-6 py-6">
        <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-lg font-bold text-slate-900">
              {menu.groups.flatMap((g) => g.items).find((i) => i.key === page)?.label ?? "홈"}
            </h1>
            {meta && <p className="text-xs text-slate-500">합성 데이터 · 상담 {meta.total_consultations.toLocaleString()}건 ({meta.start} ~ {meta.end})</p>}
          </div>
          <div className="flex items-center gap-1.5">
            <button onClick={() => setTarget((t) => shiftDate(t, -1))} className="rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs">← 전일</button>
            <input type="date" value={target} min={meta?.start} max={meta?.end} onChange={(e) => setTarget(e.target.value)}
              className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs" />
            <button onClick={() => setTarget((t) => shiftDate(t, 1))} disabled={!!meta && target >= meta.end}
              className="rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs disabled:opacity-40">익일 →</button>
          </div>
        </header>

        {target && page === "monitoring" && meta && <Monitoring target={target} dimensions={meta.decompose_dimensions} />}
        {target && page === "funnel" && <FunnelPage target={target} />}
        {target && page === "forecast" && <ForecastCard asOf={target} />}
        {page === "success_fee" && <SuccessFeeCard />}
        {target && page === "recommend" && <RecommendPanel asOf={target} />}
        {page === "home" && <p className="text-sm text-slate-500">열 수 있는 메뉴가 없습니다. 관리자에게 권한을 요청하세요.</p>}

        <p className="pt-6 text-center text-[11px] text-slate-400">
          모든 데이터는 시드 고정 난수로 생성한 합성 데이터입니다. 실제 조직·고객 정보를 포함하지 않습니다.
        </p>
      </main>
    </div>
  );
}

function FunnelPage({ target }: { target: string }) {
  const [snapshot, setSnapshot] = useState<SnapshotResponse | null>(null);
  const [rows, setRows] = useState<DrilldownRow[]>([]);
  const [dimension, setDimension] = useState("branch");
  useEffect(() => {
    let stale = false;
    api.snapshot(target).then((s) => { if (!stale) setSnapshot(s); });
    return () => { stale = true; };
  }, [target]);
  useEffect(() => {
    let stale = false;
    api.drilldown(dimension, shiftDate(target, -29), target).then((d) => { if (!stale) setRows(d.rows); });
    return () => { stale = true; };
  }, [target, dimension]);
  const cur = snapshot?.current;
  const delta = snapshot?.delta_pct ?? {};
  const base = snapshot?.baseline ?? {};
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        콜 인입일 코호트: 그날 들어온 콜이 나중에 어디까지 갔는지 본다.
        {cur && cur.calls > 0 && cur.contracts === 0 && " 최근 콜은 아직 선임 단계까지 가지 않았을 수 있다(코호트 미성숙)."}
      </p>
      {cur && (
        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <KpiCard label="콜 인입" value={cur.calls} suffix="건" deltaPct={delta.calls} baseline={base.calls} />
          <KpiCard label="예약" value={cur.reservations} suffix="건" deltaPct={delta.reservations} baseline={base.reservations}
            hint={`예약 전환율 ${cur.reservation_rate}%`} />
          <KpiCard label="선임" value={cur.contracts} suffix="건" deltaPct={delta.contracts} baseline={base.contracts}
            hint={`최종 전환율 ${cur.overall_rate}%`} />
          <KpiCard label="약정금" value={Math.round(cur.revenue / 10000)} suffix="만원" deltaPct={delta.revenue} />
        </section>
      )}
      <section className="grid gap-4 lg:grid-cols-2">
        {cur && <FunnelChart data={cur} />}
        {snapshot && <TrendChart history={snapshot.history} current={snapshot.current} />}
      </section>
      <DrilldownTable rows={rows} dimension={dimension} onChange={setDimension} />
    </div>
  );
}
