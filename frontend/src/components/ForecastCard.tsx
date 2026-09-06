import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { won, type ForecastResponse } from "../lib/api";

/** 당월 매출 예측(pacing 방식) + 지난 달 실적 비교. */
export default function ForecastCard({ data }: { data: ForecastResponse }) {
  const chart = [
    ...data.history.map((h) => ({ month: h.month.slice(2), revenue: h.revenue, forecast: false })),
    { month: data.month.slice(2), revenue: data.forecast, forecast: true },
  ];
  const progress = Math.round((data.elapsed_days / data.total_days) * 100);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-800">{data.month} 매출 예측</h2>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
          신뢰도 {data.confidence} · 표본 {data.samples}개월
        </span>
      </div>

      <div className="mt-3 flex items-baseline gap-2">
        <span className="text-2xl font-bold tabular-nums text-slate-900">
          {won(data.forecast)}
        </span>
        <span className="text-xs text-slate-500">
          예상 구간 {won(data.lower)} ~ {won(data.upper)}
        </span>
      </div>

      <div className="mt-3 text-xs text-slate-500">
        {data.elapsed_days}/{data.total_days}일 경과 · 누적 {won(data.month_to_date)} · 과거 같은
        시점 평균 진척률 {data.pace_ratio !== null ? `${(data.pace_ratio * 100).toFixed(1)}%` : "—"}
      </div>
      <div className="mt-1.5 h-1.5 rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-slate-800" style={{ width: `${progress}%` }} />
      </div>

      <div className="mt-4 h-40">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chart} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef1f5" vertical={false} />
            <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#94a3b8" }} tickLine={false} />
            <Tooltip
              formatter={(v) => won(Number(v ?? 0))}
              contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
            />
            <Bar dataKey="revenue" radius={[3, 3, 0, 0]}>
              {chart.map((entry, i) => (
                <Cell key={i} fill={entry.forecast ? "#6366f1" : "#cbd5e1"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-[11px] text-slate-400">회색 = 실적 · 보라 = 예측</p>
    </div>
  );
}
