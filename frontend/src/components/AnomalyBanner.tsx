import type { AnomalyResponse } from "../lib/api";

const LABELS: Record<string, string> = {
  calls: "콜 인입",
  reservations: "예약 수",
  contracts: "계약 수",
  reservation_rate: "예약 전환율",
  overall_rate: "최종 전환율",
};

/** 이상 판정 결과. 정상일 때도 "무엇을 확인했는지"를 보여준다. */
export default function AnomalyBanner({ data }: { data: AnomalyResponse }) {
  const flagged = data.findings.filter((f) => f.flagged);

  if (!data.anomalous) {
    return (
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
        <div className="text-sm font-semibold text-emerald-800">정상 범위</div>
        <p className="mt-0.5 text-xs text-emerald-700">
          {data.date} ({data.weekday}) — 지표 {data.findings.length}개 모두 최근 12주 같은 요일
          분포 안에 있습니다
          {flagged.length > 0 && ` (단일 지표 ${flagged.length}개 경고, 판정 기준 ${data.min_metrics}개 미만)`}
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-rose-800">이상 감지</span>
        <span className="rounded-full bg-rose-200 px-2 py-0.5 text-[11px] font-medium text-rose-900">
          지표 {data.flagged_count}개 동시 이탈
        </span>
      </div>
      <ul className="mt-2 space-y-1">
        {flagged.map((f) => (
          <li key={f.metric} className="text-xs text-rose-800">
            <span className="font-medium">{LABELS[f.metric] ?? f.metric}</span> {f.direction} —{" "}
            <span className="tabular-nums">{f.value.toLocaleString()}</span> (기준 중앙값{" "}
            {f.baseline_median.toLocaleString()}, {f.relative_deviation}% 차이, z={f.robust_z})
          </li>
        ))}
      </ul>
    </div>
  );
}
