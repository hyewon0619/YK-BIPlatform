import type { Funnel } from "../lib/api";

const STAGES = [
  { key: "calls", label: "콜 인입", color: "bg-slate-700" },
  { key: "reservations", label: "예약", color: "bg-indigo-600" },
  { key: "visits", label: "방문", color: "bg-sky-500" },
  { key: "contracts", label: "계약", color: "bg-emerald-500" },
] as const;

/** 단계별 잔존 수와 앞 단계 대비 전환율을 같이 보여준다. */
export default function FunnelChart({ data }: { data: Funnel }) {
  const max = data.calls || 1;
  const rates = [null, data.reservation_rate, data.visit_rate, data.contract_rate];

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-800">전환 퍼널</h2>
      <p className="mt-0.5 text-xs text-slate-500">
        콜 인입일 기준 코호트 · 최종 전환율 {data.overall_rate}%
      </p>

      <div className="mt-4 space-y-3">
        {STAGES.map((stage, i) => {
          const value = data[stage.key];
          const width = Math.max((value / max) * 100, 2);
          return (
            <div key={stage.key}>
              <div className="flex items-baseline justify-between text-xs">
                <span className="font-medium text-slate-700">{stage.label}</span>
                <span className="tabular-nums text-slate-900">
                  {value.toLocaleString()}
                  {rates[i] !== null && (
                    <span className="ml-1.5 text-slate-400">직전 대비 {rates[i]}%</span>
                  )}
                </span>
              </div>
              <div className="mt-1 h-2.5 overflow-hidden rounded-full bg-slate-100">
                <div
                  className={`h-full rounded-full ${stage.color} transition-all`}
                  style={{ width: `${width}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
