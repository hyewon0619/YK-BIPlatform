import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { Funnel } from "../lib/api";

/** 최근 N주 같은 요일 추세. 요일 효과를 제거하고 보기 위한 차트. */
export default function TrendChart({ history, current }: { history: Funnel[]; current: Funnel }) {
  const data = [...history, current].map((d) => ({
    date: d.date.slice(5),
    콜: d.calls,
    예약: d.reservations,
    계약: d.contracts,
  }));

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-800">같은 요일 추세</h2>
      <p className="mt-0.5 text-xs text-slate-500">
        요일 효과가 커서 전일 대비는 의미가 없다 — 같은 요일끼리 비교한다
      </p>
      <div className="mt-4 h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef1f5" />
            <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} />
            <Tooltip
              contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
            />
            <Line type="monotone" dataKey="콜" stroke="#334155" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="예약" stroke="#4f46e5" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="계약" stroke="#10b981" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
