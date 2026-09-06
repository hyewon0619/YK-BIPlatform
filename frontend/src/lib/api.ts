/** 백엔드 API 래퍼. vite proxy 가 /api 를 :8000 으로 넘긴다. */

export type Funnel = {
  date: string;
  calls: number;
  reservations: number;
  visits: number;
  contracts: number;
  revenue: number;
  success_fee: number;
  reservation_rate: number;
  visit_rate: number;
  contract_rate: number;
  overall_rate: number;
  value_per_contract: number;
  revenue_per_call: number;
};

export type SnapshotResponse = {
  current: Funnel;
  history: Funnel[];
  baseline: Record<string, number>;
  delta_pct: Record<string, number>;
  weeks: number;
};

export type DrilldownRow = {
  name: string;
  calls: number;
  reservations: number;
  visits: number;
  contracts: number;
  revenue: number;
  overall_rate: number;
  revenue_share: number;
  revenue_per_call: number;
};

export type Finding = {
  metric: string;
  value: number;
  baseline_median: number;
  robust_z: number;
  relative_deviation: number;
  direction: string;
  flagged: boolean;
};

export type AnomalyResponse = {
  date: string;
  weekday: string;
  anomalous: boolean;
  flagged_count: number;
  min_metrics: number;
  threshold: number;
  findings: Finding[];
};

export type ForecastResponse = {
  as_of: string;
  month: string;
  elapsed_days: number;
  total_days: number;
  month_to_date: number;
  forecast: number;
  lower: number;
  upper: number;
  pace_ratio: number | null;
  confidence: string;
  samples: number;
  history: { month: string; revenue: number }[];
};

export type Meta = { start: string; end: string; total_consultations: number; dimensions: string[] };

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => get<Meta>("/api/meta"),
  snapshot: (target: string, weeks = 12) =>
    get<SnapshotResponse>(`/api/funnel/snapshot?target=${target}&weeks=${weeks}`),
  series: (start: string, end: string) =>
    get<Funnel[]>(`/api/funnel/series?start=${start}&end=${end}`),
  drilldown: (dimension: string, start: string, end: string) =>
    get<{ label: string; rows: DrilldownRow[] }>(
      `/api/drilldown?dimension=${dimension}&start=${start}&end=${end}`
    ),
  cancelReasons: (start: string, end: string) =>
    get<{ total: number; rows: { name: string; total: number; share: number }[] }>(
      `/api/drilldown/cancel-reasons?start=${start}&end=${end}`
    ),
  anomaly: (target: string) => get<AnomalyResponse>(`/api/anomaly?target=${target}`),
  forecast: (asOf: string) => get<ForecastResponse>(`/api/forecast/revenue?as_of=${asOf}`),
};

/** 원 단위를 억/만 단위 한글로 줄여 표기한다. */
export function won(value: number): string {
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(1)}억`;
  if (value >= 10_000) return `${Math.round(value / 10_000).toLocaleString()}만`;
  return value.toLocaleString();
}

export function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}
