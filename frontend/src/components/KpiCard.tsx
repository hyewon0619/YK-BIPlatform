type Props = {
  label: string;
  value: number;
  suffix?: string;
  deltaPct?: number;
  baseline?: number;
  hint?: string;
};

/** 지표 1개 + 최근 12주 같은 요일 평균 대비 증감. */
export default function KpiCard({ label, value, suffix = "", deltaPct, baseline, hint }: Props) {
  const up = (deltaPct ?? 0) > 0;
  const flat = deltaPct === undefined || Math.abs(deltaPct) < 0.05;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-bold tabular-nums text-slate-900">
          {value.toLocaleString()}
        </span>
        {suffix && <span className="text-sm text-slate-500">{suffix}</span>}
      </div>
      <div className="mt-2 flex items-center gap-1.5 text-xs">
        {flat ? (
          <span className="text-slate-400">변화 없음</span>
        ) : (
          <span
            className={`font-semibold ${up ? "text-emerald-600" : "text-rose-600"}`}
            title="최근 12주 같은 요일 평균 대비"
          >
            {up ? "▲" : "▼"} {Math.abs(deltaPct!).toFixed(1)}%
          </span>
        )}
        {baseline !== undefined && (
          <span className="text-slate-400">
            (12주 평균 {baseline.toLocaleString()}
            {suffix})
          </span>
        )}
      </div>
      {hint && <div className="mt-1 text-[11px] text-slate-400">{hint}</div>}
    </div>
  );
}
