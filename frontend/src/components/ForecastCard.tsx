import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { api, won, type Forecast, type PreviousMonth, type SuccessFee } from "../lib/api";

const COLOR = { green: "text-emerald-600", orange: "text-amber-600", red: "text-rose-600" } as const;

/** ① 당월 매출 예측: 확정 + 추심예정 + 신규예상. 이번 달/지난달 토글. */
export default function ForecastCard({ asOf }: { asOf: string }) {
  const [view, setView] = useState<"current" | "previous">("current");
  const [cur, setCur] = useState<Forecast | null>(null);
  const [prev, setPrev] = useState<PreviousMonth | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    // 날짜를 빨리 바꾸면 먼저 보낸 요청이 늦게 도착해 화면을 덮어쓸 수 있다. 지난 요청의 응답은 버린다.
    let stale = false;
    setError("");
    const p = view === "current"
      ? api.forecast(asOf).then((d) => { if (!stale) setCur(d); })
      : api.previousMonth(asOf).then((d) => { if (!stale) setPrev(d); });
    // 상세 조회가 실패하면 스피너만 풀지 않고 에러 문구를 보여 준다.
    p.catch((e) => { if (!stale) setError(`불러오지 못했습니다: ${e}`); });
    return () => { stale = true; };
  }, [asOf, view]);

  const toggle = (
    <div className="flex gap-1">
      {(["current", "previous"] as const).map((v) => (
        <button key={v} onClick={() => setView(v)}
          className={`rounded-md px-2.5 py-1 text-xs font-medium ${view === v ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"}`}>
          {v === "current" ? "이번 달" : "지난달"}
        </button>
      ))}
    </div>
  );

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-800">온라인 신규 사건 입금</h2>
        {toggle}
      </div>
      {error && <p className="mt-3 text-xs text-rose-600">{error}</p>}

      {view === "previous" && prev && !error && (
        <div className="mt-3">
          <div className="text-xs text-slate-500">{prev.month} 확정 입금</div>
          <div className="text-2xl font-bold tabular-nums text-slate-900">{won(prev.confirmed.total)}원</div>
          <p className="mt-1 text-xs text-slate-500">
            당일 착수금 {won(prev.confirmed.same_day)} + 추심 입금 {won(prev.confirmed.collected)} + 환불 {won(prev.confirmed.refund)}
          </p>
        </div>
      )}

      {view === "current" && cur && !error && (
        <>
          <div className="mt-3 flex flex-wrap items-baseline gap-3">
            <span className="text-2xl font-bold tabular-nums text-slate-900">{won(cur.forecast)}원</span>
            {cur.achievement !== null && (
              <span className={`text-sm font-semibold ${COLOR[cur.color ?? "red"]}`}>
                목표 {won(cur.target ?? 0)} 대비 {cur.achievement}%
              </span>
            )}
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
            <Part label="확정 입금" value={cur.confirmed.total}
              note={`당일 ${won(cur.confirmed.same_day)} · 추심 ${won(cur.confirmed.collected)} · 환불 ${won(cur.confirmed.refund)}`} />
            <Part label="추심 예정" value={cur.scheduled.expected}
              note={`미납 원금 ${won(cur.scheduled.principal)} × 연체 구간별 확률`} />
            <Part label="신규 예상" value={cur.new_inflow.value} note={cur.formula} />
          </div>
          <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
            미수금 예상액 <b>{won(cur.scheduled.uncollected_expected)}원</b> — 회수하러 가야 할 금액
            <span className="ml-1 text-amber-700">
              ({cur.scheduled.buckets.map((b) => `${b.bucket} ${won(b.principal)}`).join(" · ")})
            </span>
          </div>
          <p className="mt-2 text-[11px] text-slate-400">{cur.elapsed_days}/{cur.total_days}일 경과 · 지난달까지는 확정 입금 실적</p>
          <div className="mt-2 h-36">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={[...cur.history.map((h) => ({ month: h.month.slice(2), v: h.confirmed, f: false })),
                { month: cur.month.slice(2), v: cur.forecast, f: true }]}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eef1f5" vertical={false} />
                <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#94a3b8" }} tickLine={false} />
                <Tooltip formatter={(v) => `${won(Number(v ?? 0))}원`} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                <Bar dataKey="v" radius={[3, 3, 0, 0]}>
                  {[...cur.history, null].map((h, i) => <Cell key={i} fill={h ? "#cbd5e1" : "#6366f1"} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}

function Part({ label, value, note }: { label: string; value: number; note: string }) {
  return (
    <div className="rounded-lg bg-slate-50 p-2.5">
      <div className="text-slate-500">{label}</div>
      <div className="mt-0.5 text-base font-semibold tabular-nums text-slate-900">{won(value)}</div>
      <div className="mt-0.5 text-[11px] leading-snug text-slate-400">{note}</div>
    </div>
  );
}

export function SuccessFeeCard() {
  const [data, setData] = useState<SuccessFee | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.successFee().then(setData).catch((e) => setError(String(e))); }, []);
  if (error) return <p className="text-xs text-rose-600">{error}</p>;
  if (!data) return <p className="text-sm text-slate-400">불러오는 중…</p>;
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-800">성공보수 실현 추정</h2>
      <div className="mt-2 text-2xl font-bold tabular-nums text-slate-900">{won(data.expected)}원</div>
      <p className="mt-1 text-xs text-slate-500">
        진행 중 약정 {data.pending_count.toLocaleString()}건 · 최대 예상액 {won(data.pending_max)}원 × 발생확률 × 수령비율
      </p>
      <ul className="mt-3 space-y-1 text-xs">
        {Object.entries(data.by_major).map(([k, v]) => (
          <li key={k} className="flex justify-between"><span className="text-slate-600">{k}</span><span className="tabular-nums">{won(v)}원</span></li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-slate-400">
        추정 단위: {Object.entries(data.levels_used).map(([k, v]) => `${k} ${v}건`).join(" · ")} (표본 20건 미만이면 상위 분류)
      </p>
    </div>
  );
}
